"""Dos workers reclaman el mismo recordatorio: solo uno envia.

El reclamo es ``UPDATE appointments SET reminder_24h_sent_at = now WHERE id =
:id AND reminder_24h_sent_at IS NULL``. En Postgres real dos sesiones que lo
corren a la vez ven rowcount 1 y 0; en SQLite no hay concurrencia y el test
seria una mentira.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from core.database import _apply_tenant_context, set_tenant_context
from modules.appointments.repository import AppointmentRepository
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import register_and_login

pytestmark = pytest.mark.postgres


async def _turno_para_manana(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> tuple[str, datetime]:
    store, token = await register_and_login(
        client, sessions, slug="recordatorio", email="recordatorio@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-rec@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=1)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=15, minute=0, second=0, microsecond=0)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Recordado",
            "client_email": "recordado@demo.com",
            "client_phone": "+5491155550777",
            "idempotency_key": "recordatorio-pg-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    appointment_id = str(reserva.json()["public_id"])
    # Reservado hace tres dias: si no, la regla "solo si la reserva es anterior
    # al momento del recordatorio" lo saltearia (se acaba de crear).
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            await session.execute(
                text(
                    "UPDATE appointments SET created_at = starts_at - interval '3 days' "
                    "WHERE id = :id"
                ),
                {"id": appointment_id},
            )
            await session.commit()
        finally:
            set_tenant_context(None, False)
    return appointment_id, slot


@pytest.mark.asyncio
async def test_dos_workers_reclaman_el_mismo_recordatorio_y_solo_uno_envia(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appointment_id, slot = await _turno_para_manana(client, app_sessions)
    enviados: list[dict[str, Any]] = []

    async def buzon(**kwargs: Any) -> dict[str, str]:
        enviados.append(kwargs["details"])
        return {"status": "sent", "channel": "email", "to": ""}

    monkeypatch.setattr(tasks, "notify_client_reminder", buzon)
    # El job usa AsyncSessionFactory; aca se lo apunta al engine de la app.
    monkeypatch.setattr(tasks, "AsyncSessionFactory", app_sessions)

    # 23 horas antes del turno: toca el de 24h y todavia no el de 2h.
    now = slot - timedelta(hours=23)
    resultados = await asyncio.gather(
        tasks.process_due_appointment_reminders(now=now),
        tasks.process_due_appointment_reminders(now=now),
    )

    assert sum(int(r["published"]) for r in resultados) == 1
    assert len(enviados) == 1
    assert enviados[0]["stage"] == "24h"

    # La marca quedo persistida: una tercera corrida no manda nada.
    tercera = await tasks.process_due_appointment_reminders(now=now)
    assert tercera["published"] == 0

    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            repo = AppointmentRepository(session)
            reclamo_tardio = await repo.claim_reminder(
                appointment_id, "reminder_24h_sent_at", now
            )
            assert reclamo_tardio is False
            assert await repo.claim_reminder(appointment_id, "reminder_2h_sent_at", now)
        finally:
            set_tenant_context(None, False)
