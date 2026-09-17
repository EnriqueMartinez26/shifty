"""Carrera bloqueo contra reserva, en Postgres real (Fase 1).

Antes ``book`` leia los bloqueos antes de tomar el lock del profesional y el
alta de bloqueos no tomaba lock alguno: una reserva podia colarse dentro de
un bloqueo recien creado. Ahora ambos toman ``FOR UPDATE`` sobre el
profesional, asi que a lo sumo uno de los dos gana.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_reserva_y_bloqueo_concurrentes_no_dejan_un_turno_adentro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="carrera-bloqueo", email="carrera-bloqueo@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-carrera@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    for intento in range(5):
        reserva, bloqueo = await asyncio.gather(
            client.post(
                "/public/appointments",
                json={
                    "store_public_id": store,
                    "service_id": service,
                    "staff_id": staff,
                    "starts_at": (slot + timedelta(hours=intento)).isoformat(),
                    "client_name": "Carrera",
                    "client_phone": f"+54911555{intento:05d}",
                    "idempotency_key": f"pg-carrera-{intento:03d}",
                },
            ),
            client.post(
                "/appointment-blocks/",
                headers=auth_headers(token),
                json={
                    "staff_id": staff,
                    "starts_at": (slot + timedelta(hours=intento)).isoformat(),
                    "ends_at": (
                        slot + timedelta(hours=intento, minutes=45)
                    ).isoformat(),
                    "reason": "Carrera",
                },
            ),
        )
        assert reserva.status_code < 500 and bloqueo.status_code < 500, (
            reserva.text,
            bloqueo.text,
        )
        assert not (reserva.status_code == 201 and bloqueo.status_code == 201), (
            "reserva y bloqueo ganaron a la vez",
            reserva.text,
            bloqueo.text,
        )

    # Invariante final: ningun turno activo dentro de un bloqueo activo.
    async with owner_engine.connect() as conn:
        huerfanos = (
            await conn.execute(
                text(
                    "select count(*) from appointments a join appointment_blocks b "
                    "on b.staff_id = a.staff_id and b.is_active "
                    "and b.start_time < a.ends_at and b.end_time > a.starts_at "
                    "where a.status in ('pending','pending_payment','confirmed')"
                )
            )
        ).scalar_one()
    assert huerfanos == 0


# ---------------------------------------------------------------------------
# Audit B1-05 (2026-09-17): la misma carrera, pero al REPROGRAMAR.
#
# ``reschedule`` (panel) y ``client_reschedule_appointment`` (cliente) leian
# los bloqueos ANTES de tomar el lock del profesional: se leia "no hay
# bloqueo", el dueno creaba el bloqueo y commiteaba, y la reprogramacion
# insertaba el turno nuevo adentro. La exclusion GiST no lo atrapa (mira
# turnos contra turnos, no contra bloqueos). Ahora el lock va antes de la
# lectura, igual que en book(): a lo sumo uno de los dos gana.
# ---------------------------------------------------------------------------


async def _sin_huerfanos(owner_engine: AsyncEngine) -> None:
    """Invariante final: ningun turno activo dentro de un bloqueo activo."""
    async with owner_engine.connect() as conn:
        huerfanos = (
            await conn.execute(
                text(
                    "select count(*) from appointments a join appointment_blocks b "
                    "on b.staff_id = a.staff_id and b.is_active "
                    "and b.start_time < a.ends_at and b.end_time > a.starts_at "
                    "where a.status in ('pending','pending_payment','confirmed')"
                )
            )
        ).scalar_one()
    assert huerfanos == 0


async def _turnos_originales(
    client: AsyncClient,
    *,
    store: str,
    service: str,
    staff: str,
    dia: datetime,
    phone: str,
    prefijo: str,
    cantidad: int,
) -> list[str]:
    """Reserva ``cantidad`` turnos del mismo cliente (09:00 UTC + i horas)."""
    turnos: list[str] = []
    for i in range(cantidad):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=9 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": "Reprogramar",
                "client_phone": phone,
                "idempotency_key": f"{prefijo}-original-{i:03d}",
            },
        )
        assert reserva.status_code == 201, reserva.text
        turnos.append(reserva.json()["public_id"])
    return turnos


async def _reprogramar_y_bloquear_a_la_vez(
    client: AsyncClient,
    *,
    token: str,
    staff: str,
    turnos: list[str],
    destino: datetime,
    reprogramar: Callable[[str, datetime, int], Awaitable[Response]],
) -> None:
    """Por cada turno: reprogramarlo y bloquear el destino en paralelo.

    Nunca 5xx y nunca ganan los dos (mismo criterio que la carrera del alta).
    """
    for intento, turno in enumerate(turnos):
        nuevo_inicio = destino + timedelta(hours=intento)
        reprogramacion, bloqueo = await asyncio.gather(
            reprogramar(turno, nuevo_inicio, intento),
            client.post(
                "/appointment-blocks/",
                headers=auth_headers(token),
                json={
                    "staff_id": staff,
                    "starts_at": nuevo_inicio.isoformat(),
                    "ends_at": (nuevo_inicio + timedelta(minutes=45)).isoformat(),
                    "reason": "Carrera reprogramacion",
                },
            ),
        )
        assert reprogramacion.status_code < 500 and bloqueo.status_code < 500, (
            reprogramacion.text,
            bloqueo.text,
        )
        assert not (reprogramacion.status_code == 200 and bloqueo.status_code == 201), (
            "reprogramacion y bloqueo ganaron a la vez",
            reprogramacion.text,
            bloqueo.text,
        )


@pytest.mark.asyncio
async def test_reprogramacion_del_panel_y_bloqueo_concurrentes_no_dejan_un_turno_adentro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client,
        app_sessions,
        slug="carrera-repro-panel",
        email="carrera-repro-panel@demo.com",
    )
    service = await create_service(client, token)
    staff = await create_staff(
        client, token, service, email="pro-carrera-repro-panel@demo.com"
    )
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    turnos = await _turnos_originales(
        client,
        store=store,
        service=service,
        staff=staff,
        dia=dia,
        phone="+5491155560001",
        prefijo="pg-repro-panel",
        cantidad=5,
    )

    async def reprogramar(turno: str, nuevo_inicio: datetime, i: int) -> Response:
        return await client.patch(
            f"/appointments/{turno}/reschedule",
            headers=auth_headers(token),
            json={
                "new_starts_at": nuevo_inicio.isoformat(),
                "idempotency_key": f"pg-repro-panel-{i:03d}",
            },
        )

    # Destino: 14:00 UTC + i horas (11:00 local en adelante), lejos del origen.
    await _reprogramar_y_bloquear_a_la_vez(
        client,
        token=token,
        staff=staff,
        turnos=turnos,
        destino=dia.replace(hour=14, minute=0, second=0, microsecond=0),
        reprogramar=reprogramar,
    )
    await _sin_huerfanos(owner_engine)


@pytest.mark.asyncio
async def test_reprogramacion_del_cliente_y_bloqueo_concurrentes_no_dejan_un_turno_adentro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, token = await register_and_login(
        client,
        app_sessions,
        slug="carrera-repro-cliente",
        email="carrera-repro-cliente@demo.com",
    )
    service = await create_service(client, token)
    staff = await create_staff(
        client, token, service, email="pro-carrera-repro-cliente@demo.com"
    )
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    telefono = "+5491155560002"
    turnos = await _turnos_originales(
        client,
        store=store,
        service=service,
        staff=staff,
        dia=dia,
        phone=telefono,
        prefijo="pg-repro-cliente",
        cantidad=5,
    )

    # El cliente valida su telefono por OTP para autogestionar.
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": telefono, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": telefono,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text

    async def reprogramar(turno: str, nuevo_inicio: datetime, i: int) -> Response:
        return await client.patch(
            f"/public/client/appointments/{turno}/reschedule",
            json={
                "phone": telefono,
                "new_starts_at": nuevo_inicio.isoformat(),
                "idempotency_key": f"pg-repro-cliente-{i:03d}",
            },
        )

    await _reprogramar_y_bloquear_a_la_vez(
        client,
        token=token,
        staff=staff,
        turnos=turnos,
        destino=dia.replace(hour=14, minute=0, second=0, microsecond=0),
        reprogramar=reprogramar,
    )
    await _sin_huerfanos(owner_engine)
