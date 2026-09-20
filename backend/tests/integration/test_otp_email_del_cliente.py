"""El OTP de un telefono que ya es cliente solo llega al email de ese cliente.

B4-01 (2026-09-18, Alta): ``request_code`` mandaba el codigo al email que
venia en el payload, elegido por quien pedia, y ``verify_code`` marcaba
``verified_at`` para el TELEFONO. Pedir el OTP de un telefono ajeno con el
email propio alcanzaba para "verificar" ese telefono durante 30 minutos:
adoptar su contacto (``get_or_create_client(adopt_contact=True)``), leer su
historial para la sena y autogestionar sus turnos.

Decision (coordinador, con OK global del usuario): si el telefono ya es de un
cliente de la tienda con email entregable, el codigo SOLO va a ese email, y
el email tipeado tiene que coincidir (normalizado). Si no coincide: respuesta
neutra con la misma forma, nadie recibe codigo y el codigo guardado no lo
conoce nadie. Si el telefono no es cliente, o su cliente no tiene email
entregable, el comportamiento es el de siempre.
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

import modules.notifications.tasks as tasks
from core.exceptions import OTPException
from modules.otp.model import OtpVerification
from modules.otp.service import OtpService
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

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
    # Sin ``x-raw-response``: el desenvuelto de tests en core/router.py arma
    # una respuesta nueva sin las background tasks, y el envio del codigo
    # corre ahi (B4-01). El camino normal las conserva, como en produccion.
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
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    tienda, store_id = await _tienda_con_cliente(
        client, test_session, "otp-cliente-ok", email_cliente=EMAIL_CLIENTE
    )

    # Mayusculas y espacios no cuentan: se compara normalizado.
    status, cuerpo = await _pedir(client, tienda, "DUENIO@example.com")
    assert status == 200, cuerpo
    assert [destino for destino, _, _ in buzon.enviados] == [EMAIL_CLIENTE]
    assert cuerpo["debug_code"] in buzon.enviados[0][2]

    servicio = OtpService(test_session)
    await servicio.verify_code(
        store_id=store_id, phone=TELEFONO_CLIENTE, code=str(cuerpo["debug_code"])
    )
    assert await servicio.is_recently_verified(
        store_id=store_id, phone=TELEFONO_CLIENTE
    )


@pytest.mark.asyncio
async def test_email_distinto_respuesta_neutra_y_nadie_recibe_el_codigo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    tienda, store_id = await _tienda_con_cliente(
        client, test_session, "otp-cliente-ajeno", email_cliente=EMAIL_CLIENTE
    )

    status_ok, exito = await _pedir(client, tienda, EMAIL_CLIENTE)
    buzon.enviados.clear()
    status, neutra = await _pedir(client, tienda, "atacante@example.com")

    # Misma forma que el exito: nada revela que el telefono es cliente ni
    # cual es su email.
    assert status == status_ok == 200
    assert set(neutra) == set(exito)
    assert neutra["ok"] is True
    assert EMAIL_CLIENTE not in str(neutra)
    # Nadie recibe el CODIGO: al email tipeado le llega el aviso sin codigo
    # de AUD2-B4-05 y al del cliente no le llega nada.
    assert [destino for destino, _, _ in buzon.enviados] == ["atacante@example.com"]
    assert _sin_codigo(buzon.enviados)

    # El codigo de la respuesta (solo existe en modo debug) no verifica, y
    # el telefono no queda verificado para quien lo pidio.
    servicio = OtpService(test_session)
    with pytest.raises(OTPException):
        await servicio.verify_code(
            store_id=store_id, phone=TELEFONO_CLIENTE, code=str(neutra["debug_code"])
        )
    assert not await servicio.is_recently_verified(
        store_id=store_id, phone=TELEFONO_CLIENTE
    )


@pytest.mark.asyncio
async def test_email_distinto_tarda_lo_mismo_que_el_exito(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hace el mismo trabajo de base (invalidar + guardar + commit) que el
    exito. Con el SMTP falso instantaneo, los tiempos quedan en el mismo orden;
    el costo del SMTP real queda documentado en el commit."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
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
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    tienda, _ = await register_and_login(
        client, slug="otp-telefono-nuevo", email="otp-telefono-nuevo@example.com"
    )
    status, cuerpo = await _pedir(client, tienda, "nuevo@example.com")
    assert status == 200, cuerpo
    assert [destino for destino, _, _ in buzon.enviados] == ["nuevo@example.com"]


@pytest.mark.asyncio
async def test_cliente_sin_email_entregable_sigue_como_siempre(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    tienda, _ = await _tienda_con_cliente(
        client,
        test_session,
        "otp-cliente-noreply",
        email_cliente=f"{TELEFONO_CLIENTE}@storeX.noreply",
    )
    status, cuerpo = await _pedir(client, tienda, "real@example.com")
    assert status == 200, cuerpo
    assert [destino for destino, _, _ in buzon.enviados] == ["real@example.com"]


# ---------------------------------------------------------------------------
# Ajuste del coordinador (2026-09-19): con SMTP de verdad, "cliente + email
# distinto" (sin envio) respondia mas rapido que los caminos con envio y el
# tiempo volvia a decir si un numero es cliente. El envio sale del request en
# todos los caminos: la respuesta no espera al SMTP.
# ---------------------------------------------------------------------------


class _Agenda:
    """Hace de BackgroundTasks: guarda los trabajos para correrlos despues."""

    def __init__(self) -> None:
        self.trabajos: list[tuple[Any, tuple[Any, ...]]] = []

    def __call__(self, func: Any, *args: Any) -> None:
        self.trabajos.append((func, args))

    async def correr(self) -> None:
        for func, args in self.trabajos:
            await func(*args)


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
    agenda = _Agenda()

    respuesta = await OtpService(test_session).request_code(
        store_id=store_id,
        phone=TELEFONO_CLIENTE,
        channel="email",
        email=EMAIL_CLIENTE,
        store_name="Demo",
        schedule_dispatch=agenda,
    )

    # Al volver el request: codigo guardado y commiteado, SMTP sin tocar.
    assert buzon.enviados == []
    assert len(agenda.trabajos) == 1
    guardado = await test_session.scalar(
        select(OtpVerification.id).where(
            OtpVerification.store_id == store_id,
            OtpVerification.consumed_at.is_(None),
        )
    )
    assert guardado is not None

    await agenda.correr()
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

        agenda = _Agenda()
        event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
        try:
            await servicio.request_code(
                store_id=store_id,
                phone=telefono,
                channel="email",
                email=email,
                store_name="Demo",
                schedule_dispatch=agenda,
            )
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)
        return sentencias, len(agenda.trabajos)

    coincide, envios_ok = await trabajo(TELEFONO_CLIENTE, EMAIL_CLIENTE)
    distinto, envios_neutros = await trabajo(TELEFONO_CLIENTE, "atacante@example.com")
    nuevo, envios_nuevo = await trabajo("5491166660000", "nuevo@example.com")

    assert coincide == distinto == nuevo, (coincide, distinto, nuevo)
    # Ninguno manda en linea. Los tres encolan exactamente un envio: el
    # camino "email distinto" manda el aviso sin codigo de AUD2-B4-05, asi
    # la entrega tampoco distingue si el telefono es cliente.
    assert buzon.enviados == []
    assert (envios_ok, envios_neutros, envios_nuevo) == (1, 1, 1)


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
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
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
    assert _sin_codigo(buzon.enviados), (
        "el codigo salio al email del atacante: el cliente guardado con 00 "
        "no se encontro"
    )
    buzon.enviados.clear()

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
    assert [destino for destino, _, _ in buzon.enviados] == [EMAIL_CLIENTE]
