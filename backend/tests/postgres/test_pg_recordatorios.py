"""Dos workers programan una sola fila durable por etapa.

La marca de etapa y la fila ``email.send`` se escriben en la misma transaccion.
En Postgres real dos sesiones concurrentes deben producir una sola fila; en
SQLite no hay concurrencia y el test seria una mentira.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from core.database import _apply_tenant_context, set_tenant_context
from modules.appointments.model import Appointment
from modules.appointments.repository import AppointmentRepository
from modules.appointments.service import ReminderScheduleService
from core.uow import AsyncSqlAlchemyUnitOfWork
from modules.payments.model import OutboxMessage
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
            "accepts_terms": True,
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
async def test_dos_workers_programan_una_sola_fila_durable(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appointment_id, slot = await _turno_para_manana(client, app_sessions)
    # El job usa AsyncSessionFactory; aca se lo apunta al engine de la app.
    monkeypatch.setattr(tasks, "AsyncSessionFactory", app_sessions)

    # 23 horas antes del turno: toca el de 24h y todavia no el de 2h.
    now = slot - timedelta(hours=23)
    resultados = await asyncio.gather(
        tasks.process_due_appointment_reminders(now=now),
        tasks.process_due_appointment_reminders(now=now),
    )

    assert sum(int(r["published"]) for r in resultados) == 1

    # La marca y el email pendiente quedaron persistidos; una tercera corrida
    # no crea otra fila aunque el dispatcher todavia no se haya ejecutado.
    tercera = await tasks.process_due_appointment_reminders(now=now)
    assert tercera["published"] == 0

    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            filas = list(
                (
                    await session.scalars(
                        select(OutboxMessage).where(
                            OutboxMessage.event_type == "email.send",
                            OutboxMessage.payload["logical_id"].as_string()
                            == f"reminder:{appointment_id}:24h",
                        )
                    )
                ).all()
            )
            assert len(filas) == 1
            assert filas[0].processed_at is None
            assert filas[0].payload["mail"] == "reminder"
            assert filas[0].payload["expires_at"] == slot.isoformat()
            repo = AppointmentRepository(session)
            reclamo_tardio = await repo.claim_reminder(
                appointment_id, "reminder_24h_sent_at", now
            )
            assert reclamo_tardio is False
            assert await repo.claim_reminder(appointment_id, "reminder_2h_sent_at", now)
        finally:
            set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_error_al_insertar_el_outbox_revierte_la_marca_del_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appointment_id, slot = await _turno_para_manana(client, app_sessions)
    payload = {
        "mail": "reminder",
        "args": {"email": "recordado@demo.com", "details": {"stage": "24h"}},
        "logical_id": f"reminder:{appointment_id}:24h",
        "expires_at": slot.isoformat(),
    }

    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            original_add = session.add

            def reject_outbox(instance: Any, **kwargs: Any) -> None:
                if isinstance(instance, OutboxMessage):
                    raise RuntimeError("outbox insert failed")
                original_add(instance, **kwargs)

            monkeypatch.setattr(session, "add", reject_outbox)
            uow = AsyncSqlAlchemyUnitOfWork(session)
            async with uow:
                reminder_service = ReminderScheduleService(uow)
                with pytest.raises(RuntimeError, match="outbox insert failed"):
                    await reminder_service.schedule_reminder(
                        appointment_id=appointment_id,
                        column="reminder_24h_sent_at",
                        scheduled_at=slot - timedelta(hours=23),
                        payload=payload,
                    )
        finally:
            set_tenant_context(None, False)

    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            appointment = await session.get(Appointment, appointment_id)
            assert appointment is not None
            assert appointment.reminder_24h_sent_at is None
            rows = list(
                (
                    await session.scalars(
                        select(OutboxMessage).where(
                            OutboxMessage.payload["logical_id"].as_string()
                            == f"reminder:{appointment_id}:24h"
                        )
                    )
                ).all()
            )
            assert rows == []
        finally:
            set_tenant_context(None, False)
