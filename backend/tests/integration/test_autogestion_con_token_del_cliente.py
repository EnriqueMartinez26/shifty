"""La autogestion exige el token del cliente que devuelve ``/public/otp/verify``.

Hallazgo del 2026-10-14: "Mis turnos" (listar, cancelar, reprogramar) y la
lista de espera publica (``/mine``, ``/leave``) se autorizaban solo con
``is_client_contact_verified``: "hay una verificacion OTP de (tienda,
telefono) contra el email de la ficha en los ultimos 30 minutos". Ese
predicado no esta atado a QUIEN pregunta: ``/public/otp/verify`` no devolvia
nada que el navegador tuviera que presentar despues. Durante esos 30 minutos,
cualquiera que supiera el ``store_public_id`` (publico) y el telefono podia,
desde otro dispositivo, listar los turnos de esa persona (nombre, servicios,
horarios) y cancelarlos o reprogramarlos.

Ahora verificar devuelve un token opaco y corto (``client_token``) atado a la
tienda, al telefono, al email verificado y a la verificacion concreta, y cada
camino de autogestion lo exige en ``X-Client-Token`` ADEMAS del chequeo en la
base. Faltante, invalido o de otro telefono o tienda: el mismo 403 neutro
``OTP_VERIFICATION_REQUIRED`` de siempre (regla 20).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from core.security import create_access_token, decode_token
from modules.appointments.model import Appointment
from modules.otp.model import OtpVerification
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_caracterizacion_alta_publica import _reserva, _Tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

HEADER = "X-Client-Token"
TEL_A = "+5491155558101"
TEL_B = "+5491155558102"


@pytest.fixture(autouse=True)
def _otp_de_consola(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    monkeypatch.setattr(tasks, "_send_email", Buzon())


async def _tienda(client: AsyncClient, slug: str) -> _Tienda:
    """Como la de la caracterizacion, con el email del profesional por tienda:
    hay tests con dos tiendas y el email del personal es unico global."""
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@test.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    return _Tienda(store, token, service, staff, slot)


def _digitos(telefono: str) -> str:
    return telefono.lstrip("+")


def _email(t: _Tienda, telefono: str) -> str:
    # Uno por tienda: la suite de SQLite no tiene el unico POR TIENDA de PV-01.
    return f"{_digitos(telefono)}-{t.store.lower()}@example.com"


async def _reservar(
    client: AsyncClient, t: _Tienda, telefono: str, clave: str, *, horas: int = 0
) -> str:
    res = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            clave,
            client_phone=telefono,
            client_email=_email(t, telefono),
            starts_at=(t.slot + timedelta(hours=horas)).isoformat(),
        ),
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _verificar(client: AsyncClient, t: _Tienda, telefono: str) -> dict[str, Any]:
    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": t.store,
            "phone": telefono,
            "channel": "email",
            # El mismo email de la ficha (``_reservar``): el codigo va ahi.
            "email": _email(t, telefono),
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": t.store,
            "phone": telefono,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text
    return dict(verificado.json())


async def _token(client: AsyncClient, t: _Tienda, telefono: str) -> str:
    return str((await _verificar(client, t, telefono))["client_token"])


async def _estado(session: AsyncSession, turno: str) -> str:
    session.expire_all()
    return str(
        await session.scalar(select(Appointment.status).where(Appointment.id == turno))
    )


async def _turnos(session: AsyncSession) -> int:
    session.expire_all()
    return int(await session.scalar(select(func.count()).select_from(Appointment)) or 0)


def _rechazo_neutro(res: Any) -> None:
    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "OTP_VERIFICATION_REQUIRED", res.text


async def _listar(
    client: AsyncClient, t: _Tienda, telefono: str, token: str | None
) -> Any:
    return await client.get(
        f"/public/client/{t.store}/{_digitos(telefono)}/appointments",
        headers={HEADER: token} if token is not None else {},
    )


async def _cancelar(
    client: AsyncClient, turno: str, telefono: str, token: str | None
) -> Any:
    return await client.patch(
        f"/public/client/appointments/{turno}/cancel",
        json={"phone": telefono, "reason": "no puedo"},
        headers={HEADER: token} if token is not None else {},
    )


async def _reprogramar(
    client: AsyncClient,
    t: _Tienda,
    turno: str,
    telefono: str,
    token: str | None,
    clave: str,
) -> Any:
    return await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": telefono,
            "new_starts_at": (t.slot + timedelta(hours=3)).isoformat(),
            "idempotency_key": clave,
        },
        headers={HEADER: token} if token is not None else {},
    )


async def _tres_rechazos(
    client: AsyncClient,
    session: AsyncSession,
    t: _Tienda,
    turno: str,
    telefono: str,
    token: str | None,
    clave: str,
) -> None:
    """Listar, reprogramar y cancelar rebotan, y la base no cambia."""
    turnos_antes = await _turnos(session)
    estado_antes = await _estado(session, turno)

    _rechazo_neutro(await _listar(client, t, telefono, token))
    _rechazo_neutro(await _reprogramar(client, t, turno, telefono, token, clave))
    _rechazo_neutro(await _cancelar(client, turno, telefono, token))

    assert await _estado(session, turno) == estado_antes
    assert await _turnos(session) == turnos_antes


# ---------------------------------------------------------------------------
# El token: emision y separacion del access token del panel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verificar_devuelve_un_token_del_cliente(client: AsyncClient) -> None:
    t = await _tienda(client, "tok-emision")
    await _reservar(client, t, TEL_A, "tok-emision-0001")

    cuerpo = await _verificar(client, t, TEL_A)

    assert isinstance(cuerpo.get("client_token"), str) and cuerpo["client_token"]
    # Lo de antes sigue igual: el cambio es aditivo.
    assert cuerpo["ok"] is True
    assert cuerpo["phone"] == TEL_A


@pytest.mark.asyncio
async def test_el_token_del_cliente_no_es_un_access_token_del_panel(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "tok-panel")
    await _reservar(client, t, TEL_A, "tok-panel-0001")
    token = await _token(client, t, TEL_A)

    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token)
    me = await client.get("/me", headers=auth_headers(token))
    assert me.status_code == 401, me.text


@pytest.mark.asyncio
async def test_un_access_token_del_panel_no_es_un_token_del_cliente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "tok-acceso")
    turno = await _reservar(client, t, TEL_A, "tok-acceso-0001")
    await _verificar(client, t, TEL_A)

    # El del admin de la tienda, y uno forjado con los claims del cliente.
    await _tres_rechazos(
        client, test_session, t, turno, TEL_A, t.token, "tok-acceso-repro-1"
    )
    forjado = create_access_token(
        data={"sub": "x", "store": "x", "phone": TEL_A, "purpose": "client"}
    )
    await _tres_rechazos(
        client, test_session, t, turno, TEL_A, forjado, "tok-acceso-repro-2"
    )


# ---------------------------------------------------------------------------
# IDOR: la verificacion de otro no alcanza
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otro_dispositivo_sin_token_no_lista_reprograma_ni_cancela(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El cliente A verifica; un segundo "dispositivo" sin su token no entra."""
    t = await _tienda(client, "tok-idor")
    turno = await _reservar(client, t, TEL_A, "tok-idor-0001")
    await _verificar(client, t, TEL_A)

    await _tres_rechazos(client, test_session, t, turno, TEL_A, None, "tok-idor-r1")
    await _tres_rechazos(client, test_session, t, turno, TEL_A, "", "tok-idor-r2")
    await _tres_rechazos(client, test_session, t, turno, TEL_A, "basura", "tok-idor-r3")


@pytest.mark.asyncio
async def test_el_token_de_un_telefono_no_abre_otro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """A y B verificaron los dos: el token de A con el telefono de B rebota."""
    t = await _tienda(client, "tok-tel")
    await _reservar(client, t, TEL_A, "tok-tel-0001")
    turno_b = await _reservar(client, t, TEL_B, "tok-tel-0002", horas=1)
    token_a = await _token(client, t, TEL_A)
    await _verificar(client, t, TEL_B)

    await _tres_rechazos(
        client, test_session, t, turno_b, TEL_B, token_a, "tok-tel-repro"
    )


@pytest.mark.asyncio
async def test_el_token_de_una_tienda_no_abre_otra(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Mismo telefono verificado en las dos tiendas: el token de X no abre Y."""
    x = await _tienda(client, "tok-tienda-x")
    y = await _tienda(client, "tok-tienda-y")
    await _reservar(client, x, TEL_A, "tok-tienda-x-0001")
    turno_y = await _reservar(client, y, TEL_A, "tok-tienda-y-0001")
    token_x = await _token(client, x, TEL_A)
    await _verificar(client, y, TEL_A)

    await _tres_rechazos(
        client, test_session, y, turno_y, TEL_A, token_x, "tok-tienda-r"
    )


@pytest.mark.asyncio
async def test_un_token_vencido_rebota(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    from modules.otp.client_token import issue_client_token

    t = await _tienda(client, "tok-vencido")
    turno = await _reservar(client, t, TEL_A, "tok-vencido-0001")
    await _verificar(client, t, TEL_A)
    fila = (
        await test_session.execute(
            select(OtpVerification).where(OtpVerification.verified_at.is_not(None))
        )
    ).scalar_one()

    # Misma verificacion, firmado bien, pero emitido hace 31 minutos.
    vencido = issue_client_token(
        store_id=fila.store_id,
        phone=fila.phone,
        email=str(fila.email),
        verification_id=fila.id,
        verified_at=datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    await _tres_rechazos(client, test_session, t, turno, TEL_A, vencido, "tok-venc-r")


@pytest.mark.asyncio
async def test_un_token_vigente_de_una_verificacion_vieja_rebota(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Defensa en profundidad: la base sigue mandando aunque el token valga."""
    t = await _tienda(client, "tok-fila-vieja")
    turno = await _reservar(client, t, TEL_A, "tok-fila-vieja-0001")
    token = await _token(client, t, TEL_A)
    await test_session.execute(
        update(OtpVerification).values(
            verified_at=datetime.now(timezone.utc) - timedelta(minutes=31)
        )
    )
    await test_session.commit()

    await _tres_rechazos(client, test_session, t, turno, TEL_A, token, "tok-vieja-r")


def _b64(parte: dict[str, Any]) -> str:
    crudo = json.dumps(parte, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


@pytest.mark.asyncio
async def test_un_token_adulterado_rebota(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "tok-adulterado")
    await _reservar(client, t, TEL_A, "tok-adulterado-0001")
    turno_b = await _reservar(client, t, TEL_B, "tok-adulterado-0002", horas=1)
    token_a = await _token(client, t, TEL_A)
    await _verificar(client, t, TEL_B)

    cabecera, cuerpo, firma = token_a.split(".")
    # Firma tocada.
    otra_firma = ("A" if firma[0] != "A" else "B") + firma[1:]
    await _tres_rechazos(
        client,
        test_session,
        t,
        turno_b,
        TEL_B,
        f"{cabecera}.{cuerpo}.{otra_firma}",
        "tok-adult-r1",
    )
    # Cuerpo cambiado al telefono de B, con la firma original.
    claims = jwt.decode(token_a, options={"verify_signature": False})
    claims = {k: (TEL_B if v == TEL_A else v) for k, v in claims.items()}
    await _tres_rechazos(
        client,
        test_session,
        t,
        turno_b,
        TEL_B,
        f"{cabecera}.{_b64(claims)}.{firma}",
        "tok-adult-r2",
    )
    # Sin firma (alg none).
    sin_firma = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."
    await _tres_rechazos(
        client, test_session, t, turno_b, TEL_B, sin_firma, "tok-adult-r3"
    )


# ---------------------------------------------------------------------------
# El camino legitimo sigue igual
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_con_su_token_lista_reprograma_y_cancela(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "tok-legitimo")
    primero = await _reservar(client, t, TEL_A, "tok-legitimo-0001")
    segundo = await _reservar(client, t, TEL_A, "tok-legitimo-0002", horas=1)
    token = await _token(client, t, TEL_A)

    listado = await _listar(client, t, TEL_A, token)
    assert listado.status_code == 200, listado.text
    assert {a["public_id"] for a in listado.json()["appointments"]} == {
        primero,
        segundo,
    }

    movido = await _reprogramar(client, t, primero, TEL_A, token, "tok-legit-r1")
    assert movido.status_code == 200, movido.text
    assert await _estado(test_session, primero) == "cancelled"

    cancelado = await _cancelar(client, segundo, TEL_A, token)
    assert cancelado.status_code == 200, cancelado.text
    assert cancelado.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Lista de espera publica: la misma matriz
# ---------------------------------------------------------------------------


async def _anotarse(client: AsyncClient, t: _Tienda, telefono: str) -> str:
    inicio = t.slot + timedelta(hours=4)
    res = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "staff_id": t.staff,
            "window_starts_at": inicio.isoformat(),
            "window_ends_at": (inicio + timedelta(hours=1)).isoformat(),
            "client_name": "Cliente Espera",
            "client_phone": telefono,
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _abiertas(session: AsyncSession) -> int:
    session.expire_all()
    return int(
        await session.scalar(
            select(func.count())
            .select_from(WaitlistEntry)
            .where(WaitlistEntry.is_active.is_(True))
            .where(WaitlistEntry.status.in_(("waiting", "offered")))
        )
        or 0
    )


async def _espera_rechaza(
    client: AsyncClient,
    session: AsyncSession,
    t: _Tienda,
    entrada: str,
    telefono: str,
    token: str | None,
) -> None:
    abiertas = await _abiertas(session)
    headers = {HEADER: token} if token is not None else {}
    cuerpo = {"store_public_id": t.store, "phone": telefono}
    _rechazo_neutro(
        await client.post("/public/waitlist/mine", json=cuerpo, headers=headers)
    )
    _rechazo_neutro(
        await client.post(
            f"/public/waitlist/{entrada}/leave", json=cuerpo, headers=headers
        )
    )
    assert await _abiertas(session) == abiertas


@pytest.mark.asyncio
async def test_lista_de_espera_exige_el_token_del_cliente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    x = await _tienda(client, "tok-espera-x")
    y = await _tienda(client, "tok-espera-y")
    await _reservar(client, x, TEL_A, "tok-espera-0001")
    await _reservar(client, x, TEL_B, "tok-espera-0002", horas=1)
    await _reservar(client, y, TEL_A, "tok-espera-0003")
    entrada = await _anotarse(client, x, TEL_A)
    token_a = await _token(client, x, TEL_A)
    token_b = await _token(client, x, TEL_B)
    token_y = await _token(client, y, TEL_A)

    # Sin token, con el de otro telefono, con el de otra tienda, con el del
    # panel: el mismo 403 neutro, y la entrada sigue abierta.
    for ajeno in (None, "basura", token_b, token_y, x.token):
        await _espera_rechaza(client, test_session, x, entrada, TEL_A, ajeno)

    propio = {HEADER: token_a}
    cuerpo = {"store_public_id": x.store, "phone": TEL_A}
    mias = await client.post("/public/waitlist/mine", json=cuerpo, headers=propio)
    assert mias.status_code == 200, mias.text
    assert [e["public_id"] for e in mias.json()] == [entrada]
    baja = await client.post(
        f"/public/waitlist/{entrada}/leave", json=cuerpo, headers=propio
    )
    assert baja.status_code == 204, baja.text


# ---------------------------------------------------------------------------
# Reserva con el flag ``otp_booking``: tambien atada al token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reservar_con_otp_booking_exige_el_token(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Con el flag, la verificacion ajena tampoco alcanza para reservar."""
    t = await _tienda(client, "tok-reserva")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(t.token),
        json={"otp_booking": True},
    )
    assert flags.status_code == 200, flags.text
    token = await _token(client, t, TEL_A)
    turnos = await _turnos(test_session)

    sin_token = await client.post(
        "/public/appointments",
        json=_reserva(t, "tok-reserva-0001", client_phone=TEL_A),
    )
    _rechazo_neutro(sin_token)
    assert await _turnos(test_session) == turnos

    con_token = await client.post(
        "/public/appointments",
        json=_reserva(t, "tok-reserva-0002", client_phone=TEL_A),
        headers={HEADER: token},
    )
    assert con_token.status_code == 201, con_token.text
