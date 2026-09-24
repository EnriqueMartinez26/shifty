"""El OTP de un telefono que ya es cliente solo llega al email de ese cliente.

B4-01 (2026-09-18, Alta): ``request_code`` mandaba el codigo al email que
venia en el payload, elegido por quien pedia, y ``verify_code`` marcaba
``verified_at`` para el TELEFONO. Pedir el OTP de un telefono ajeno con el
email propio alcanzaba para "verificar" ese telefono durante 30 minutos:
adoptar su contacto (``get_or_create_client(adopt_contact=True)``), leer su
historial para la sena y autogestionar sus turnos.

Decision (coordinador, con OK global del usuario; unificada el 2026-09-23 con
el fix del front del 2026-09-20): si el telefono ya es de un cliente de la
tienda con email entregable, el codigo SOLO va a ese email, tipee lo que tipee
quien lo pide. Si el tipeado es otro, a ese le llega un aviso sin codigo
(AUD2-B4-05) y la respuesta es neutra con la misma forma. El registro guarda a
que buzon fue el codigo (``otp_verifications.email``) y la autogestion exige
que coincida con el de la ficha. Si el telefono no es cliente, o su cliente
no tiene email entregable, el comportamiento es el de siempre.
"""

from __future__ import annotations

import re
import statistics
import time
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs

import modules.notifications.tasks as tasks
from core.config import settings
from core.exceptions import OTPException
from modules.otp.model import OtpVerification
from modules.otp.service import OtpService
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_otp_por_email import Cola

TELEFONO_CLIENTE = "5491155551234"
EMAIL_CLIENTE = "duenio@example.com"

_CODIGO = re.compile(r"\b\d{6}\b")


def _sin_codigo(enviados: list[tuple[str, str, str]]) -> bool:
    """Ningun mail de la lista trae un codigo de 6 digitos.

    Desde AUD2-B4-05 el camino retenido manda un aviso SIN codigo al email
    tipeado, para que "no me llego nada" deje de decir que ese telefono es
    cliente. Lo que no puede pasar nunca es que el codigo salga ahi.
    """
    return all(not _CODIGO.search(cuerpo) for _, _, cuerpo in enviados)


async def _tienda_con_cliente(
    client: AsyncClient, session: AsyncSession, slug: str, *, email_cliente: str
) -> tuple[str, str]:
    publica, _ = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    store_id = await session.scalar(select(Store.id).where(Store.public_id == publica))
    assert store_id is not None
    session.add(
        User(
            email=email_cliente,
            hashed_password="!",
            role=UserRole.CLIENT.value,
            store_id=store_id,
            phone=TELEFONO_CLIENTE,
            full_name="Duenio del telefono",
        )
    )
    await session.commit()
    return publica, str(store_id)


async def _pedir(
    client: AsyncClient, tienda: str, email: str
) -> tuple[int, dict[str, Any]]:
    # ``x-raw-response: false`` pide el sobre canonico; el fixture ``client``
    # manda "true" por defecto. Es lo unico que decide ese header: la nota
    # anterior decia que el desenvuelto perdia las background tasks, y no era
    # cierto -las dos ramas de CanonicalJsonMiddleware clonan igual-. Desde
    # AUD2-B4-06 ya no hay background tasks en este camino: el mail se encola.
    respuesta = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": tienda,
            "phone": f"+{TELEFONO_CLIENTE}",
            "channel": "email",
            "email": email,
        },
    )
    cuerpo = respuesta.json()
    return respuesta.status_code, cuerpo.get("data", cuerpo)


@pytest.mark.asyncio
async def test_email_coincidente_recibe_el_codigo_y_verifica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda, store_id = await _tienda_con_cliente(
        client, test_session, "otp-cliente-ok", email_cliente=EMAIL_CLIENTE
    )

    # Mayusculas y espacios no cuentan: se compara normalizado.
    status, cuerpo = await _pedir(client, tienda, "DUENIO@example.com")
    assert status == 200, cuerpo
    assert [destino for destino, _, _ in cola.enviados] == [EMAIL_CLIENTE]
    assert cuerpo["debug_code"] in cola.enviados[0][2]

    servicio = OtpService(test_session)
    await servicio.verify_code(
        store_id=store_id, phone=TELEFONO_CLIENTE, code=str(cuerpo["debug_code"])
    )
    assert await servicio.is_client_contact_verified(
        store_id=store_id, phone=TELEFONO_CLIENTE
    )


@pytest.mark.asyncio
async def test_email_distinto_respuesta_neutra_y_el_codigo_solo_va_a_la_ficha(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda, store_id = await _tienda_con_cliente(
        client, test_session, "otp-cliente-ajeno", email_cliente=EMAIL_CLIENTE
    )

    status_ok, exito = await _pedir(client, tienda, EMAIL_CLIENTE)
    cola.enviados.clear()
    status, neutra = await _pedir(client, tienda, "atacante@example.com")

    # Misma forma que el exito: nada revela que el telefono es cliente ni
    # cual es su email.
    assert status == status_ok == 200
    assert set(neutra) == set(exito)
    assert neutra["ok"] is True
    assert EMAIL_CLIENTE not in str(neutra)
    # El CODIGO va solo al email de la ficha (quien pide no elige el buzon);
    # al email tipeado le llega el aviso sin codigo de AUD2-B4-05.
    assert [destino for destino, _, _ in cola.enviados] == [
        EMAIL_CLIENTE,
        "atacante@example.com",
    ]
    con_codigo = [d for d, _, cuerpo in cola.enviados if _CODIGO.search(cuerpo)]
    assert con_codigo == [EMAIL_CLIENTE]
    assert _sin_codigo([m for m in cola.enviados if m[0] != EMAIL_CLIENTE])

    # Quien pidio no tiene el codigo (fue al buzon de la ficha): el telefono
    # no queda verificado para nadie hasta que el titular lo use.
    servicio = OtpService(test_session)
    assert not await servicio.is_client_contact_verified(
        store_id=store_id, phone=TELEFONO_CLIENTE
    )


@pytest.mark.asyncio
async def test_email_distinto_el_debug_code_es_un_senuelo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AUD2-SYNC-01 (2026-09-23): el merge con origin/main dejo de devolver el
    senuelo en el camino sin coincidencia.

    Sintoma: con ``OTP_DEBUG_EXPOSE_CODE=true`` (cualquier entorno que no sea
    produccion, que lo fuerza a false), pedir el OTP de un telefono ajeno con
    la casilla propia devolvia en ``debug_code`` el codigo REAL, el mismo que
    viajaba al email de la ficha. Con eso alcanzaba para verificar el telefono
    de la victima y autogestionar sus turnos. Antes del merge (290ab9f) ese
    camino devolvia un codigo de mentira con la misma forma; esta prueba lo
    vuelve a clavar.
    """
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda, store_id = await _tienda_con_cliente(
        client, test_session, "otp-cliente-senuelo", email_cliente=EMAIL_CLIENTE
    )

    status, neutra = await _pedir(client, tienda, "atacante@example.com")
    assert status == 200, neutra
    senuelo = str(neutra["debug_code"])
    assert re.fullmatch(r"\d{6}", senuelo), "misma forma que un codigo real"

    # El codigo real es el que salio al buzon de la ficha, y es OTRO.
    con_codigo = [
        cuerpo for destino, _, cuerpo in cola.enviados if destino == EMAIL_CLIENTE
    ]
    assert len(con_codigo) == 1
    real = _CODIGO.search(con_codigo[0])
    assert real is not None
    assert real.group(0) != senuelo

    servicio = OtpService(test_session)
    with pytest.raises(OTPException):
        await servicio.verify_code(
            store_id=store_id, phone=TELEFONO_CLIENTE, code=senuelo
        )
    assert not await servicio.is_client_contact_verified(
        store_id=store_id, phone=TELEFONO_CLIENTE
    )

    # El titular, con el codigo que le llego, si verifica.
    await servicio.verify_code(
        store_id=store_id, phone=TELEFONO_CLIENTE, code=real.group(0)
    )
    assert await servicio.is_client_contact_verified(
        store_id=store_id, phone=TELEFONO_CLIENTE
    )


@pytest.mark.asyncio
async def test_canal_sin_email_no_loguea_una_falsa_falta_de_coincidencia(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AUD2-SYNC-01 (2026-09-23): ``_resolve_destination`` con ``email=None``
    (canales whatsapp/sms de desarrollo) y un cliente conocido logueaba
    ``otp_request_email_mismatch_for_known_client`` sin que nadie hubiera
    tipeado un email. Ese evento es la senal de un posible secuestro de
    contacto; un falso positivo por cada pedido por consola lo vuelve ruido.
    """
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    store_id = await _store_con_cliente_directo(test_session, "otp-sin-email-log")
    servicio = OtpService(test_session)

    with capture_logs() as sin_email:
        await servicio.request_code(
            store_id=store_id,
            phone=TELEFONO_CLIENTE,
            channel="whatsapp",
            email=None,
            store_name="Demo",
            schedule_dispatch=_Cola(),
        )
    with capture_logs() as con_email_distinto:
        await servicio.request_code(
            store_id=store_id,
            phone=TELEFONO_CLIENTE,
            channel="email",
            email="atacante@example.com",
            store_name="Demo",
            schedule_dispatch=_Cola(),
        )

    evento = "otp_request_email_mismatch_for_known_client"
    assert all(e["event"] != evento for e in sin_email), sin_email
    assert any(e["event"] == evento for e in con_email_distinto)


@pytest.mark.asyncio
async def test_email_distinto_tarda_lo_mismo_que_el_exito(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hace el mismo trabajo de base (invalidar + guardar + commit) que el
    exito. Con el SMTP falso instantaneo, los tiempos quedan en el mismo orden;
    el costo del SMTP real queda documentado en el commit."""
    monkeypatch.setattr(tasks, "send_otp_email", Cola())
    tienda, _ = await _tienda_con_cliente(
        client, test_session, "otp-cliente-tiempo", email_cliente=EMAIL_CLIENTE
    )

    async def medir(email: str) -> float:
        tiempos = []
        for _ in range(5):
            inicio = time.perf_counter()
            status, _ = await _pedir(client, tienda, email)
            tiempos.append(time.perf_counter() - inicio)
            assert status == 200
        return statistics.median(tiempos)

    exito = await medir(EMAIL_CLIENTE)
    neutra = await medir("atacante@example.com")
    assert neutra <= exito * 3 + 0.02, (exito, neutra)
    assert neutra >= exito / 3 - 0.02, (exito, neutra)


@pytest.mark.asyncio
async def test_telefono_nuevo_sigue_como_siempre(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda, _ = await register_and_login(
        client, slug="otp-telefono-nuevo", email="otp-telefono-nuevo@example.com"
    )
    status, cuerpo = await _pedir(client, tienda, "nuevo@example.com")
    assert status == 200, cuerpo
    assert [destino for destino, _, _ in cola.enviados] == ["nuevo@example.com"]


@pytest.mark.asyncio
async def test_cliente_sin_email_entregable_sigue_como_siempre(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda, _ = await _tienda_con_cliente(
        client,
        test_session,
        "otp-cliente-noreply",
        email_cliente=f"{TELEFONO_CLIENTE}@storeX.noreply",
    )
    status, cuerpo = await _pedir(client, tienda, "real@example.com")
    assert status == 200, cuerpo
    assert [destino for destino, _, _ in cola.enviados] == ["real@example.com"]


# ---------------------------------------------------------------------------
# Ajuste del coordinador (2026-09-19): con SMTP de verdad, "cliente + email
# distinto" (sin envio) respondia mas rapido que los caminos con envio y el
# tiempo volvia a decir si un numero es cliente. El envio sale del request en
# todos los caminos: la respuesta no espera al SMTP.
# ---------------------------------------------------------------------------


class _Cola:
    """Hace de cola: guarda lo que el servicio manda entregar (AUD2-B4-06).

    ``correr`` entrega lo encolado como lo haria el worker, por el cuerpo
    real de la tarea, asi el test sigue viendo el mail y no solo la
    intencion de mandarlo.
    """

    def __init__(self) -> None:
        self.encolados: list[tuple[str, str, str]] = []

    def __call__(self, to: str, subject: str, body: str) -> None:
        self.encolados.append((to, subject, body))

    async def correr(self) -> None:
        for to, subject, body in self.encolados:
            await tasks.deliver_otp_email(to, subject, body)


async def _store_con_cliente_directo(session: AsyncSession, slug: str) -> str:
    store = Store(name=f"Tienda {slug}", slug=slug)
    store.public_id = store.id
    session.add(store)
    await session.flush()
    session.add(
        User(
            email=EMAIL_CLIENTE,
            hashed_password="!",
            role=UserRole.CLIENT.value,
            store_id=store.id,
            phone=TELEFONO_CLIENTE,
            full_name="Duenio del telefono",
        )
    )
    await session.commit()
    return str(store.id)


@pytest.mark.asyncio
async def test_el_request_devuelve_sin_llamar_al_smtp_y_el_envio_va_despues(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store_id = await _store_con_cliente_directo(test_session, "otp-diferido")
    cola = _Cola()

    respuesta = await OtpService(test_session).request_code(
        store_id=store_id,
        phone=TELEFONO_CLIENTE,
        channel="email",
        email=EMAIL_CLIENTE,
        store_name="Demo",
        schedule_dispatch=cola,
    )

    # Al volver el request: codigo guardado y commiteado, SMTP sin tocar.
    assert buzon.enviados == []
    assert len(cola.encolados) == 1
    guardado = await test_session.scalar(
        select(OtpVerification.id).where(
            OtpVerification.store_id == store_id,
            OtpVerification.consumed_at.is_(None),
        )
    )
    assert guardado is not None

    await cola.correr()
    assert [destino for destino, _, _ in buzon.enviados] == [EMAIL_CLIENTE]
    assert str(respuesta["debug_code"]) in buzon.enviados[0][2]


@pytest.mark.asyncio
async def test_los_tres_caminos_hacen_el_mismo_trabajo_sincronico(
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store_id = await _store_con_cliente_directo(test_session, "otp-mismo-trabajo")
    servicio = OtpService(test_session)

    async def trabajo(telefono: str, email: str) -> tuple[list[str], int]:
        sentencias: list[str] = []

        def registrar(
            _c: Any, _cur: Any, statement: str, _p: Any, _ctx: Any, _m: bool
        ) -> None:
            sentencias.append(statement.split()[0].upper())

        cola = _Cola()
        event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
        try:
            await servicio.request_code(
                store_id=store_id,
                phone=telefono,
                channel="email",
                email=email,
                store_name="Demo",
                schedule_dispatch=cola,
            )
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)
        return sentencias, len(cola.encolados)

    coincide, envios_ok = await trabajo(TELEFONO_CLIENTE, EMAIL_CLIENTE)
    distinto, envios_neutros = await trabajo(TELEFONO_CLIENTE, "atacante@example.com")
    nuevo, envios_nuevo = await trabajo("5491166660000", "nuevo@example.com")

    assert coincide == distinto == nuevo, (coincide, distinto, nuevo)
    # Ninguno manda en linea. El camino "email distinto" encola dos envios:
    # el codigo al email de la ficha y el aviso sin codigo de AUD2-B4-05 al
    # tipeado, asi la entrega tampoco distingue si el telefono es cliente.
    assert buzon.enviados == []
    assert (envios_ok, envios_neutros, envios_nuevo) == (1, 2, 1)


# ---------------------------------------------------------------------------
# AUD2-B4-03 (2026-09-19): la guarda buscaba al cliente con normalize_phone
# (que convierte el prefijo "00" en "+"), mientras el alta publica guarda los
# digitos tal cual, con el "00" adelante. Un cliente que reservo tipeando
# "0054 9 11 5555-1234" no se encontraba: el codigo salia al email tipeado y
# el secuestro de contacto volvia a estar abierto.
# ---------------------------------------------------------------------------

TELEFONO_CON_00 = "005491155559999"


@pytest.mark.parametrize(
    "tipeado",
    [
        "005491155559999",  # como lo guardo el alta publica
        "+5491155559999",  # forma internacional
        "5491155559999",  # digitos sueltos
        "0054 9 11 5555-9999",  # con separadores
    ],
)
@pytest.mark.asyncio
async def test_el_cliente_guardado_con_00_se_encuentra_en_cualquier_forma(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tipeado: str,
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    publica, _ = await register_and_login(
        client, slug="otp-00-prefijo", email="otp-00-prefijo@example.com"
    )
    store_id = await test_session.scalar(
        select(Store.id).where(Store.public_id == publica)
    )
    assert store_id is not None
    test_session.add(
        User(
            email=EMAIL_CLIENTE,
            hashed_password="!",
            role=UserRole.CLIENT.value,
            store_id=store_id,
            phone=TELEFONO_CON_00,
            full_name="Duenio del telefono",
        )
    )
    await test_session.commit()

    respuesta = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": publica,
            "phone": tipeado,
            "channel": "email",
            "email": "atacante@example.com",
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    assert _sin_codigo([m for m in cola.enviados if m[0] != EMAIL_CLIENTE]), (
        "el codigo salio al email del atacante: el cliente guardado con 00 "
        "no se encontro"
    )
    assert [d for d, _, c in cola.enviados if _CODIGO.search(c)] == [EMAIL_CLIENTE]
    cola.enviados.clear()

    # Y con el email del cliente, en la misma forma de telefono, si sale.
    ok = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": publica,
            "phone": tipeado,
            "channel": "email",
            "email": EMAIL_CLIENTE,
        },
    )
    assert ok.status_code == 200, ok.text
    assert [destino for destino, _, _ in cola.enviados] == [EMAIL_CLIENTE]
