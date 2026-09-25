"""Caracterizacion de la autogestion del cliente antes de partirla (B1-12).

Audit B1-12 (2026-09-19), regla 29 de CLAUDE.md: ``client_cancel_appointment``
(111 lineas) y ``client_reschedule_appointment`` (200, nombrada como deuda en
CLAUDE.md §5) commiteaban en el router. Antes de moverlas a
``PublicBookingService`` estos tests fijan el camino completo tal como es
HOY: codigos y cuerpos, filas, eventos del outbox, invalidaciones del cache,
orden commit -> cache e idempotencia de la reprogramacion (reserva,
liberacion y replay). Pasan sobre la base y siguen pasando despues del
refactor sin cambiar una asercion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment
from modules.payments.model import Payment
from modules.public_api.router import _reschedule_cache_key
from modules.public_api.schemas import ClientRescheduleRequest
from tests.integration.test_caracterizacion_alta_publica import (
    _contar,
    _espiar_orden,
    _eventos,
    _redis,
    _reserva,
    _Tienda,
    _tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon

TELEFONO = "+5491155558001"


async def _verificar(client: AsyncClient, t: _Tienda) -> None:
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": t.store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": t.store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text


async def _con_turno(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
    *,
    otp: bool = True,
) -> tuple[_Tienda, str]:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, slug)
    reserva = await client.post(
        "/public/appointments", json=_reserva(t, f"{slug}-alta-0001")
    )
    assert reserva.status_code == 201, reserva.text
    if otp:
        await _verificar(client, t)
    return t, str(reserva.json()["public_id"])


async def _turno(session: AsyncSession, turno_id: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == turno_id))
    ).scalar_one()


def _sin_ids(cuerpo: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in cuerpo.items()
        if k not in {"public_id", "starts_at", "ends_at"}
    }


# ---------------------------------------------------------------------------
# Cancelacion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelar_cuerpo_filas_outbox_y_cache(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "carac-cancel")
    antes = await _eventos(test_session)
    orden = _espiar_orden(test_session, await _redis(), monkeypatch)

    res = await client.patch(
        f"/public/client/appointments/{turno}/cancel",
        json={"phone": TELEFONO, "reason": "No llego"},
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["public_id"] == turno
    assert _sin_ids(cuerpo) == {
        "service_id": t.service,
        "service_name": "Consulta",
        "staff_id": t.staff,
        "staff_name": "Pro Demo",
        "status": "cancelled",
        "client_name": "Cliente Caracterizado",
        "client_phone": "5491155558001",
        "notes": "Primera vez",
        "custom_fields": {},
        "payment_required": False,
        "payment_status": None,
        "payment_link": None,
        "payment_public_id": None,
        "payment_amount": None,
        "promotion_code": None,
        "service_price": None,
        "discount_amount": None,
        "final_price": None,
    }
    assert orden == ["commit", "cache"], orden
    fila = await _turno(test_session, turno)
    assert fila.status == "cancelled" and fila.cancelled_at is not None
    nuevos = (await _eventos(test_session))[len(antes) :]
    assert [e[0] for e in nuevos] == [
        "appointment.slot_released",
        "appointment.cancelled_by_client",
    ]
    liberado, aviso = nuevos[0][1], nuevos[1][1]
    assert liberado["reason"] == "client_cancelled"
    assert liberado["appointment_id"] == turno
    assert aviso == {
        "appointment_id": turno,
        "client_name": "Cliente Caracterizado",
        "service_name": "Consulta",
        "starts_at": aviso["starts_at"],
        "reason": "No llego",
    }
    assert ensure_utc_aware(datetime.fromisoformat(aviso["starts_at"])) == t.slot


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caso", ["inexistente", "otro_telefono", "sin_otp", "ventana", "con_cobro"]
)
async def test_cancelar_rechazos_sin_escribir(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    t, turno = await _con_turno(
        client, monkeypatch, f"carac-cr-{caso}", otp=caso != "sin_otp"
    )
    telefono = TELEFONO
    objetivo = turno
    esperado: tuple[int, str]
    if caso == "inexistente":
        objetivo = "01J00000000000000000000000"
        esperado = (404, "APPOINTMENT_NOT_FOUND")
    elif caso == "otro_telefono":
        telefono = "+5491155558999"
        esperado = (403, "PERMISSION_DENIED")
    elif caso == "sin_otp":
        esperado = (403, "OTP_VERIFICATION_REQUIRED")
    elif caso == "ventana":
        await test_session.execute(
            update(Appointment)
            .where(Appointment.id == turno)
            .values(
                starts_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                ends_at=datetime.now(timezone.utc) + timedelta(minutes=60),
            )
        )
        await test_session.commit()
        esperado = (409, "CANCELLATION_WINDOW_EXPIRED")
    else:
        await test_session.execute(
            update(Appointment)
            .where(Appointment.id == turno)
            .values(status="pending_payment")
        )
        await test_session.commit()
        esperado = (409, "PAYMENT_APPOINTMENT_REQUIRES_RELEASE")
    antes = await _eventos(test_session)
    estado_antes = (await _turno(test_session, turno)).status

    res = await client.patch(
        f"/public/client/appointments/{objetivo}/cancel", json={"phone": telefono}
    )

    assert (res.status_code, res.json()["error_code"]) == esperado, res.text
    assert await _eventos(test_session) == antes
    assert (await _turno(test_session, turno)).status == estado_antes
    assert t.store


# ---------------------------------------------------------------------------
# Reprogramacion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprogramar_cuerpo_filas_outbox_cache_y_replay(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "carac-repro")
    antes = await _eventos(test_session)
    orden = _espiar_orden(test_session, await _redis(), monkeypatch)
    nuevo_inicio = t.slot + timedelta(hours=2)
    pedido = {
        "phone": TELEFONO,
        "new_starts_at": nuevo_inicio.isoformat(),
        "idempotency_key": "carac-repro-nuevo-0001",
    }

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule", json=pedido
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["public_id"] != turno
    assert _sin_ids(cuerpo) == {
        "service_id": t.service,
        "service_name": "Consulta",
        "staff_id": t.staff,
        "staff_name": "Pro Demo",
        "status": "pending",
        "client_name": "Cliente Caracterizado",
        "client_phone": "5491155558001",
        "notes": "Primera vez",
        "custom_fields": {},
        "payment_required": False,
        "payment_status": None,
        "payment_link": None,
        "payment_public_id": None,
        "payment_amount": None,
        "promotion_code": None,
        "service_price": None,
        "discount_amount": None,
        "final_price": None,
    }
    assert ensure_utc_aware(datetime.fromisoformat(cuerpo["starts_at"])) == (
        nuevo_inicio
    )
    assert orden == ["commit", "cache"], orden
    assert (await _turno(test_session, turno)).status == "cancelled"
    nuevo = await _turno(test_session, cuerpo["public_id"])
    assert nuevo.status == "pending"
    assert nuevo.idempotency_key == "carac-repro-nuevo-0001"
    assert nuevo.price_amount == Decimal("10000.00")
    assert ensure_utc_aware(nuevo.expires_at) == nuevo_inicio  # type: ignore[arg-type]
    assert (nuevo.client_name, nuevo.client_phone) == (
        "Cliente Caracterizado",
        "5491155558001",
    )
    nuevos = (await _eventos(test_session))[len(antes) :]
    assert [(e[0], e[1]["reason"]) for e in nuevos] == [
        ("appointment.slot_released", "client_rescheduled")
    ]

    replay = await client.patch(
        f"/public/client/appointments/{turno}/reschedule", json=pedido
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == cuerpo
    assert await _contar(test_session, Appointment) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caso",
    [
        "inexistente",
        "otro_telefono",
        "sin_otp",
        "con_cobro",
        "pagado",
        "antelacion",
        "fuera_de_horario",
        "bloqueado",
        "ocupado",
    ],
)
async def test_reprogramar_rechazos_liberan_la_clave_y_no_escriben(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    t, turno = await _con_turno(
        client, monkeypatch, f"carac-rr-{caso}", otp=caso != "sin_otp"
    )
    objetivo, telefono = turno, TELEFONO
    nuevo_inicio = t.slot + timedelta(hours=2)
    esperado: tuple[int, str]
    if caso == "inexistente":
        objetivo = "01J00000000000000000000000"
        esperado = (404, "APPOINTMENT_NOT_FOUND")
    elif caso == "otro_telefono":
        telefono = "+5491155558999"
        esperado = (403, "PERMISSION_DENIED")
    elif caso == "sin_otp":
        esperado = (403, "OTP_VERIFICATION_REQUIRED")
    elif caso == "con_cobro":
        await test_session.execute(
            update(Appointment)
            .where(Appointment.id == turno)
            .values(status="pending_payment")
        )
        await test_session.commit()
        esperado = (409, "PAYMENT_APPOINTMENT_REQUIRES_RELEASE")
    elif caso == "pagado":
        fila = await _turno(test_session, turno)
        test_session.add(
            Payment(
                store_id=fila.store_id,
                appointment_id=turno,
                amount=Decimal("2500.00"),
                status="approved",
            )
        )
        await test_session.commit()
        esperado = (409, "PAID_APPOINTMENT_RESCHEDULE_DENIED")
    elif caso == "antelacion":
        nuevo_inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
        esperado = (400, "BOOKING_NOTICE_REQUIRED")
    elif caso == "fuera_de_horario":
        nuevo_inicio = t.slot + timedelta(hours=9)  # 19:00 local
        esperado = (409, "OUT_OF_SCHEDULE")
    elif caso == "bloqueado":
        bloqueo = await client.post(
            "/appointment-blocks/",
            headers=auth_headers(t.token),
            json={
                "staff_id": t.staff,
                "starts_at": nuevo_inicio.isoformat(),
                "ends_at": (nuevo_inicio + timedelta(hours=1)).isoformat(),
                "reason": "Pausa",
            },
        )
        assert bloqueo.status_code == 201, bloqueo.text
        esperado = (409, "SCHEDULE_BLOCKED")
    else:
        otra = await client.post(
            "/public/appointments",
            json=_reserva(
                t,
                "carac-rr-ocupa-0001",
                starts_at=nuevo_inicio.isoformat(),
                client_phone="+5491155558777",
                client_email="ocupa-carac@example.com",
            ),
        )
        assert otra.status_code == 201, otra.text
        esperado = (409, "APPOINTMENT_CONFLICT")
    antes = await _eventos(test_session)
    turnos_antes = await _contar(test_session, Appointment)
    estado_antes = (await _turno(test_session, turno)).status
    redis = await _redis()
    cuerpo: dict[str, Any] = {
        "phone": telefono,
        "new_starts_at": nuevo_inicio.isoformat(),
        "idempotency_key": f"carac-rr-{caso}-clave",
    }

    res = await client.patch(
        f"/public/client/appointments/{objetivo}/reschedule", json=cuerpo
    )

    assert (res.status_code, res.json()["error_code"]) == esperado, res.text
    # La clave de Redis es la namespaceada por turno y telefono (AUD2-B1-06),
    # no la cadena cruda que manda el cliente.
    clave = _reschedule_cache_key(objetivo, ClientRescheduleRequest(**cuerpo))
    assert await redis.get(f"idempotency:{clave}") is None
    assert await _eventos(test_session) == antes
    assert await _contar(test_session, Appointment) == turnos_antes
    assert (await _turno(test_session, turno)).status == estado_antes
