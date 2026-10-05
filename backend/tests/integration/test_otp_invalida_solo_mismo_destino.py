"""Un codigo OTP nuevo solo invalida los vivos que fueron a la MISMA casilla.

2026-10-05, sintoma (revision de #126): con un telefono sin ficha de cliente,
el codigo va al email que tipea quien lo pide. Guardar un codigo nuevo
consumia TODOS los vivos de ese telefono, asi que cualquiera podia pedir un
codigo para el telefono de otra persona con su PROPIA casilla: el mail salia
de verdad (la regla de #126, "solo invalidar si el mail se encolo", no lo
frena) y el codigo A que la victima tenia en su casilla X dejaba de
verificar. Un pedido por cada codigo de la victima alcanzaba para trabarle la
reserva con OTP sin que nada lo delate. ("Mis turnos" exige ficha de
cliente, y con ficha el codigo va solo al email guardado: ese camino no
cambia.)

Regla nueva: guardar un codigo invalida solo los vivos enviados al mismo
buzon (``otp_verifications.email``). Los de otras casillas siguen hasta
vencer, y la verificacion los compara a todos. Cota de fuerza bruta: cada
intento cuenta contra TODOS los codigos vivos con los que se compara, asi que
ningun codigo enfrenta mas de ``OTP_MAX_ATTEMPTS`` intentos en su vida (igual
que antes), y la verificacion mira a lo sumo ``OTP_MAX_REQUESTS_PER_HOUR``
codigos vivos por telefono. La respuesta HTTP no dice si hay otros codigos.

Residuo anterior a este arreglo, que sigue abierto: el bloqueo por
verificaciones. Cinco verificaciones anonimas erradas agotan el codigo de la
victima (``OTP_MAX_ATTEMPTS``), y diez agotan el presupuesto de verificacion
del telefono (``OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR``, compartido por todos).
Ninguna de las dos necesita una casilla.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from core.exceptions import OTPException
from modules.otp.model import OtpVerification
from modules.otp.service import OTP_GATE_EMAIL_MISMATCH, OtpService
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_otp_oraculo_por_entrega import (
    EMAIL_CLIENTE,
    TELEFONO_CLIENTE,
    _tienda_con_cliente,
)
from tests.integration.test_otp_por_email import Cola

TELEFONO = "5491160007777"
VICTIMA = "victima@example.com"
ATACANTE = "atacante@example.com"
OTRA = "otra@example.com"
_CODIGO = re.compile(r"\b\d{6}\b")

# Lo que corre un intento errado con uno y con dos codigos vivos:
# (sentencia, executemany).
UN_CODIGO_VIVO = [("SELECT", False), ("UPDATE", False)]
DOS_CODIGOS_VIVOS = [("SELECT", False), ("UPDATE", True)]


@pytest.fixture
def cola(monkeypatch: pytest.MonkeyPatch) -> Cola:
    encolados = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", encolados)
    return encolados


async def _tienda(client: AsyncClient, slug: str) -> str:
    tienda, _ = await register_and_login(client, slug=slug, email=f"{slug}@example.com")
    return tienda


async def _pedir_crudo(
    client: AsyncClient, tienda: str, email: str, *, telefono: str = TELEFONO
) -> Response:
    return await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": tienda,
            "phone": f"+{telefono}",
            "channel": "email",
            "email": email,
        },
    )


async def _pedir(
    client: AsyncClient, tienda: str, email: str, *, telefono: str = TELEFONO
) -> None:
    respuesta = await _pedir_crudo(client, tienda, email, telefono=telefono)
    assert respuesta.status_code == 200, respuesta.text


async def _verificar(
    client: AsyncClient, tienda: str, codigo: str, *, telefono: str = TELEFONO
) -> Response:
    return await client.post(
        "/public/otp/verify",
        headers={"x-raw-response": "false"},
        json={"store_public_id": tienda, "phone": f"+{telefono}", "code": codigo},
    )


async def _verifica(
    client: AsyncClient, tienda: str, codigo: str, *, telefono: str = TELEFONO
) -> bool:
    respuesta = await _verificar(client, tienda, codigo, telefono=telefono)
    assert respuesta.status_code in {200, 400}, respuesta.text
    return respuesta.status_code == 200


def _ultimo_codigo(cola: Cola, destino: str) -> str:
    cuerpos = [cuerpo for to, _, cuerpo in cola.enviados if to == destino]
    assert cuerpos, f"no se encolo nada para {destino}"
    encontrado = _CODIGO.search(cuerpos[-1])
    assert encontrado is not None, "el ultimo mail a ese buzon no trae codigo"
    return encontrado.group(0)


def _otro_codigo(*conocidos: str) -> str:
    """Un codigo de 6 digitos que no es ninguno de los vivos."""
    for candidato in range(1_000_000):
        texto = f"{candidato:06d}"
        if texto not in conocidos:
            return texto
    raise AssertionError("inalcanzable")


async def _intentos_por_buzon(
    session: AsyncSession, tienda: str, telefono: str = TELEFONO
) -> dict[str, int]:
    """``attempts`` de cada codigo VIVO del telefono, por buzon de destino."""
    store_id = await session.scalar(select(Store.id).where(Store.public_id == tienda))
    filas = await session.execute(
        select(OtpVerification.email, OtpVerification.attempts).where(
            OtpVerification.store_id == store_id,
            OtpVerification.phone == f"+{telefono}",
            OtpVerification.consumed_at.is_(None),
        )
    )
    return {str(email): int(intentos) for email, intentos in filas.all()}


@pytest.mark.asyncio
async def test_el_codigo_de_la_victima_sobrevive_al_pedido_a_otra_casilla(
    client: AsyncClient, cola: Cola
) -> None:
    """2026-10-05: pedir un codigo para el telefono ajeno con la casilla
    propia mataba el codigo A que la victima tenia en la suya."""
    tienda = await _tienda(client, "otp-destino-victima")
    await _pedir(client, tienda, VICTIMA)
    codigo_a = _ultimo_codigo(cola, VICTIMA)

    await _pedir(client, tienda, ATACANTE)
    codigo_b = _ultimo_codigo(cola, ATACANTE)

    assert await _verifica(client, tienda, codigo_a), (
        "el pedido a otra casilla invalido el codigo vivo de la victima"
    )
    # El del atacante tambien verifica (prueba SU casilla, no la de la
    # victima), y verificar uno no consume el otro.
    if codigo_b != codigo_a:  # 1 en 10^6 de que coincidan
        assert await _verifica(client, tienda, codigo_b)


@pytest.mark.asyncio
async def test_verificar_el_codigo_propio_no_consume_el_de_la_victima(
    client: AsyncClient, cola: Cola
) -> None:
    """El atacante usa su codigo primero: el de la victima sigue vivo."""
    tienda = await _tienda(client, "otp-destino-orden")
    await _pedir(client, tienda, VICTIMA)
    codigo_a = _ultimo_codigo(cola, VICTIMA)
    await _pedir(client, tienda, ATACANTE)
    codigo_b = _ultimo_codigo(cola, ATACANTE)
    if codigo_b == codigo_a:  # 1 en 10^6: el mismo numero no prueba nada
        return

    assert await _verifica(client, tienda, codigo_b)
    assert await _verifica(client, tienda, codigo_a)


@pytest.mark.asyncio
async def test_un_pedido_a_la_misma_casilla_reemplaza_al_vivo(
    client: AsyncClient, cola: Cola
) -> None:
    """Sin cambios: un codigo nuevo a la MISMA casilla invalida el anterior."""
    tienda = await _tienda(client, "otp-destino-misma")
    await _pedir(client, tienda, VICTIMA)
    codigo_a = _ultimo_codigo(cola, VICTIMA)
    # Mayusculas y espacios no hacen otra casilla: se compara normalizado.
    await _pedir(client, tienda, " Victima@Example.com ")
    codigo_a2 = _ultimo_codigo(cola, VICTIMA)
    if codigo_a2 == codigo_a:  # 1 en 10^6
        return

    assert not await _verifica(client, tienda, codigo_a)
    assert await _verifica(client, tienda, codigo_a2)


@pytest.mark.asyncio
async def test_con_ficha_de_cliente_el_codigo_sigue_yendo_solo_a_la_ficha(
    client: AsyncClient, test_session: AsyncSession, cola: Cola
) -> None:
    """Camino de la ficha sin cambios (``test_otp_email_del_cliente.py``):
    todo codigo va al email guardado, asi que "misma casilla" es "todos los
    codigos del telefono" y un pedido nuevo reemplaza al vivo, tipee lo que
    tipee quien pide. Al tipeado le llega el aviso sin codigo."""
    tienda = await _tienda_con_cliente(client, test_session, "otp-destino-ficha")
    await _pedir(client, tienda, EMAIL_CLIENTE, telefono=TELEFONO_CLIENTE)
    codigo_a = _ultimo_codigo(cola, EMAIL_CLIENTE)
    cola.enviados.clear()

    await _pedir(client, tienda, ATACANTE, telefono=TELEFONO_CLIENTE)

    con_codigo = [to for to, _, cuerpo in cola.enviados if _CODIGO.search(cuerpo)]
    assert con_codigo == [EMAIL_CLIENTE]
    assert sorted(to for to, _, _ in cola.enviados) == sorted([EMAIL_CLIENTE, ATACANTE])
    assert await _intentos_por_buzon(test_session, tienda, TELEFONO_CLIENTE) == {
        EMAIL_CLIENTE: 0
    }, "quedo vivo un codigo a otro buzon que el de la ficha"
    codigo_b = _ultimo_codigo(cola, EMAIL_CLIENTE)
    if codigo_b != codigo_a:  # 1 en 10^6
        assert not await _verifica(client, tienda, codigo_a, telefono=TELEFONO_CLIENTE)
    assert await _verifica(client, tienda, codigo_b, telefono=TELEFONO_CLIENTE)


@pytest.mark.asyncio
async def test_cada_intento_cuenta_contra_todos_los_codigos_vivos(
    client: AsyncClient, test_session: AsyncSession, cola: Cola
) -> None:
    """Cota de fuerza bruta: con N codigos vivos un intento se compara con
    los N, asi que cuenta contra los N. Ningun codigo ve mas de
    ``OTP_MAX_ATTEMPTS`` intentos en su vida: agotado, ni el codigo correcto
    pasa (429, como antes con un solo codigo)."""
    tienda = await _tienda(client, "otp-destino-intentos")
    await _pedir(client, tienda, VICTIMA)
    codigo_a = _ultimo_codigo(cola, VICTIMA)
    await _pedir(client, tienda, ATACANTE)
    codigo_b = _ultimo_codigo(cola, ATACANTE)
    errado = _otro_codigo(codigo_a, codigo_b)

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        assert not await _verifica(client, tienda, errado)

    assert await _intentos_por_buzon(test_session, tienda) == {
        VICTIMA: settings.OTP_MAX_ATTEMPTS,
        ATACANTE: settings.OTP_MAX_ATTEMPTS,
    }
    agotado = await _verificar(client, tienda, codigo_a)
    assert agotado.status_code == 429, agotado.text


@pytest.mark.asyncio
async def test_un_codigo_nuevo_no_le_devuelve_intentos_al_de_la_victima(
    client: AsyncClient, test_session: AsyncSession, cola: Cola
) -> None:
    """Pedir un codigo fresco a la casilla propia no reabre el de la victima:
    agotado queda fuera de la comparacion, y los intentos siguientes se
    comparan solo con el fresco."""
    tienda = await _tienda(client, "otp-destino-sin-reset")
    await _pedir(client, tienda, VICTIMA)
    codigo_a = _ultimo_codigo(cola, VICTIMA)
    await _pedir(client, tienda, ATACANTE)
    errado = _otro_codigo(codigo_a, _ultimo_codigo(cola, ATACANTE))
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        assert not await _verifica(client, tienda, errado)

    await _pedir(client, tienda, ATACANTE)
    codigo_c = _ultimo_codigo(cola, ATACANTE)
    if codigo_c == codigo_a:  # 1 en 10^6: el mismo numero no prueba nada
        return

    assert not await _verifica(client, tienda, codigo_a)
    assert await _intentos_por_buzon(test_session, tienda) == {
        VICTIMA: settings.OTP_MAX_ATTEMPTS,
        ATACANTE: 1,
    }


@pytest.mark.asyncio
async def test_la_verificacion_mira_a_lo_sumo_el_presupuesto_de_pedidos(
    client: AsyncClient, cola: Cola, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cota dura de N: aunque el presupuesto por telefono de Redis no corra
    (desarrollo, tests), un intento se compara con a lo sumo
    ``OTP_MAX_REQUESTS_PER_HOUR`` codigos vivos, los mas nuevos."""
    monkeypatch.setattr(settings, "OTP_MAX_REQUESTS_PER_HOUR", 2)
    tienda = await _tienda(client, "otp-destino-cota")
    codigos = []
    for casilla in (VICTIMA, ATACANTE, OTRA):
        await _pedir(client, tienda, casilla)
        codigos.append(_ultimo_codigo(cola, casilla))
    if len(set(codigos)) < 3:  # 3 en 10^6
        return

    assert not await _verifica(client, tienda, codigos[0])
    assert await _verifica(client, tienda, codigos[2])
    assert await _verifica(client, tienda, codigos[1])


def _forma(respuesta: Response) -> tuple[int, Any]:
    cuerpo: dict[str, Any] = respuesta.json()
    data = cuerpo.get("data") or {}
    return respuesta.status_code, (sorted(cuerpo), sorted(data))


def _error(respuesta: Response) -> tuple[int, Any]:
    cuerpo: dict[str, Any] = respuesta.json()
    return respuesta.status_code, cuerpo.get("error")


@pytest.mark.asyncio
async def test_la_respuesta_no_dice_si_hay_otros_codigos(
    client: AsyncClient,
    test_session: AsyncSession,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Produccion (sin debug_code): pedir con o sin otros codigos vivos, a la
    misma casilla o a otra, con o sin ficha, responde igual; y un intento
    errado responde igual con cero, uno o dos codigos vivos."""
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", False)
    tienda = await _tienda(client, "otp-destino-forma")
    con_ficha = await _tienda_con_cliente(
        client, test_session, "otp-destino-forma-ficha"
    )

    sin_codigos = await _verificar(client, tienda, "123456")
    primero = await _pedir_crudo(client, tienda, VICTIMA)
    errado_uno = await _verificar(
        client, tienda, _otro_codigo(_ultimo_codigo(cola, VICTIMA))
    )
    otra_casilla = await _pedir_crudo(client, tienda, ATACANTE)
    misma_casilla = await _pedir_crudo(client, tienda, VICTIMA)
    errado_dos = await _verificar(
        client,
        tienda,
        _otro_codigo(_ultimo_codigo(cola, VICTIMA), _ultimo_codigo(cola, ATACANTE)),
    )
    ficha = await _pedir_crudo(client, con_ficha, ATACANTE, telefono=TELEFONO_CLIENTE)

    assert _forma(primero)[0] == 200
    assert (
        _forma(primero)
        == _forma(otra_casilla)
        == _forma(misma_casilla)
        == _forma(ficha)
    )
    assert _error(sin_codigos)[0] == 400
    assert _error(sin_codigos) == _error(errado_uno) == _error(errado_dos)


async def _store_directo(session: AsyncSession, slug: str) -> str:
    store = Store(name=f"Tienda {slug}", slug=slug)
    store.public_id = store.id
    session.add(store)
    await session.commit()
    return str(store.id)


def _encolado(_to: str, _subject: str, _body: str) -> bool:
    return True


@pytest.mark.asyncio
async def test_verificar_con_uno_o_dos_codigos_vivos(
    test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """Senal de tiempo debil y acotada: un intento errado corre las mismas
    sentencias con uno o con dos codigos vivos, pero con dos el UPDATE de
    intentos va como executemany sobre las dos filas (y el SELECT lockea
    dos). Se fija esa diferencia exacta para que ningun cambio la agrande
    sin que este test lo diga."""
    store_id = await _store_directo(test_session, "otp-destino-paridad")
    servicio = OtpService(test_session)

    async def pedir(email: str) -> str:
        respuesta = await servicio.request_code(
            store_id=store_id,
            phone=f"+{TELEFONO}",
            channel="email",
            email=email,
            store_name="Demo",
            schedule_dispatch=_encolado,
        )
        return str(respuesta["debug_code"])

    async def intento_errado(errado: str) -> list[tuple[str, bool]]:
        sentencias: list[tuple[str, bool]] = []

        def registrar(
            _c: Any, _cur: Any, statement: str, _p: Any, _ctx: Any, many: bool
        ) -> None:
            sentencias.append((statement.split()[0].upper(), many))

        event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
        try:
            with pytest.raises(OTPException):
                await servicio.verify_code(
                    store_id=store_id, phone=f"+{TELEFONO}", code=errado
                )
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)
        return sentencias

    codigo_a = await pedir(VICTIMA)
    uno = await intento_errado(_otro_codigo(codigo_a))
    codigo_b = await pedir(ATACANTE)
    dos = await intento_errado(_otro_codigo(codigo_a, codigo_b))

    assert uno == UN_CODIGO_VIVO, uno
    assert dos == DOS_CODIGOS_VIVOS, dos


@pytest.mark.asyncio
async def test_el_codigo_del_atacante_no_abre_la_ficha_creada_despues(
    client: AsyncClient, test_session: AsyncSession, cola: Cola
) -> None:
    """Fija el caso borde de la regla: el atacante pide un codigo a SU casilla
    para un telefono sin ficha; despues se crea la ficha con el email de la
    victima y la victima pide el suyo. El codigo del atacante fue a otro
    buzon, asi que sigue vivo y verifica, pero prueba SU casilla: "Mis
    turnos" y la reserva con OTP siguen cerrados (OTP_GATE_EMAIL_MISMATCH)."""
    tienda = await _tienda(client, "otp-destino-ficha-despues")
    store_id = await test_session.scalar(
        select(Store.id).where(Store.public_id == tienda)
    )
    assert store_id is not None
    await _pedir(client, tienda, ATACANTE)
    codigo_atacante = _ultimo_codigo(cola, ATACANTE)

    test_session.add(
        User(
            email=VICTIMA,
            hashed_password="!",
            role=UserRole.CLIENT.value,
            store_id=store_id,
            phone=TELEFONO,
            full_name="Victima",
        )
    )
    await test_session.commit()
    await _pedir(client, tienda, VICTIMA)
    if _ultimo_codigo(cola, VICTIMA) == codigo_atacante:  # 1 en 10^6
        return

    assert await _verifica(client, tienda, codigo_atacante)

    mis_turnos = await client.get(f"/public/client/{tienda}/{TELEFONO}/appointments")
    assert mis_turnos.status_code == 403, mis_turnos.text
    servicio = OtpService(test_session)
    assert (
        await servicio.booking_otp_reason(store_id=store_id, phone=f"+{TELEFONO}")
        == OTP_GATE_EMAIL_MISMATCH
    )
    assert not await servicio.may_book_with_otp(store_id=store_id, phone=f"+{TELEFONO}")
