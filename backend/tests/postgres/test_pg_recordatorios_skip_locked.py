"""S-06: el scheduler de recordatorios con SKIP LOCKED, contra Postgres real.

2026-09-18, seguimiento de la revision de B4-02: ``get_upcoming_for_reminders``
selecciona filas con ``FOR UPDATE SKIP LOCKED`` (regla 8). La marca de etapa y
su fila ``email.send`` quedan en el mismo commit. Aca:

1. Un turno bloqueado por otra transaccion se saltea sin esperar (sin SKIP
   LOCKED la corrida quedaba colgada hasta el ``lock_timeout`` del rol) y sale
   en la corrida siguiente, cuando el lock se libera.
2. Dos corridas a la vez programan una fila durable por recordatorio, con la
   etapa correcta: el de 2 horas al turno proximo y el de 24 horas a los demas.

En SQLite no hay locks: ``tests/integration/test_recordatorios_skip_locked.py``
solo puede verificar la sentencia.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from core.database import _apply_tenant_context, set_tenant_context
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import register_and_login

pytestmark = pytest.mark.postgres


async def _turnos_de_manana(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> tuple[dict[str, str], datetime]:
    """Cuatro turnos manana (10, 12, 14 y 16 UTC) reservados hace tres dias."""
    store, token = await register_and_login(
        client, sessions, slug="recordatorio-skip", email="rec-skip@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-skip@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=1)
    await add_staff_schedule(client, token, staff, target_date=dia)

    turnos: dict[str, str] = {}
    primero = dia.replace(hour=10, minute=0, second=0, microsecond=0)
    for indice, hora in enumerate((10, 12, 14, 16)):
        slot = primero.replace(hour=hora)
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": slot.isoformat(),
                "client_name": f"Cliente {hora}",
                "client_email": f"skip-{hora}@demo.com",
                "client_phone": f"+54911555{indice:05d}",
                "accepts_terms": True,
                "idempotency_key": f"recordatorio-skip-{indice:06d}",
            },
        )
        assert reserva.status_code == 201, reserva.text
        turnos[f"{hora}h"] = str(reserva.json()["public_id"])

    # Reservados hace tres dias: si no, la regla "solo si la reserva es
    # anterior al momento del recordatorio" los saltearia.
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            await session.execute(
                text(
                    "UPDATE appointments SET created_at = starts_at - interval '3 days' "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": list(turnos.values())},
            )
            await session.commit()
        finally:
            set_tenant_context(None, False)
    return turnos, primero


async def _scheduled_reminders(
    sessions: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str]]:
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            rows = (
                await session.scalars(
                    select(OutboxMessage).where(
                        OutboxMessage.event_type == "email.send"
                    )
                )
            ).all()
            return sorted(
                (
                    str(row.payload["appointment_id"]),
                    str(row.payload["logical_id"]).rsplit(":", 1)[-1],
                )
                for row in rows
                if row.payload.get("source_event") == "appointment.reminder"
            )
        finally:
            set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_un_turno_bloqueado_se_saltea_sin_esperar_y_sale_despues(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turnos, primero = await _turnos_de_manana(client, app_sessions)
    monkeypatch.setattr(tasks, "AsyncSessionFactory", app_sessions)
    # 06:00 UTC de manana: los cuatro (a 4, 6, 8 y 10 horas) estan en la etapa
    # de 24 horas y ninguno en la de 2.
    now = primero.replace(hour=6)

    bloqueado = turnos["14h"]
    async with app_sessions() as otra:
        set_tenant_context(None, True)
        await _apply_tenant_context(otra)
        await otra.execute(
            text("SELECT id FROM appointments WHERE id = :id FOR UPDATE"),
            {"id": bloqueado},
        )
        # Sin SKIP LOCKED esta corrida espera el lock (y cae por lock_timeout).
        resultado = await asyncio.wait_for(
            tasks.process_due_appointment_reminders(now=now), timeout=4
        )
        await otra.rollback()

    assert resultado["published"] == 3
    assert {
        appointment_id for appointment_id, _ in await _scheduled_reminders(app_sessions)
    } == (set(turnos.values()) - {bloqueado})

    # Liberado el lock, la corrida siguiente persiste solo el que faltaba.
    siguiente = await tasks.process_due_appointment_reminders(now=now)
    assert siguiente["published"] == 1
    assert await _scheduled_reminders(app_sessions) == sorted(
        (appointment_id, "24h") for appointment_id in turnos.values()
    )


@pytest.mark.asyncio
async def test_dos_corridas_a_la_vez_persisten_una_fila_por_recordatorio(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turnos, primero = await _turnos_de_manana(client, app_sessions)
    monkeypatch.setattr(tasks, "AsyncSessionFactory", app_sessions)
    # 08:30 UTC: el de las 10 esta a 1h30 (toca el de 2 horas y NO el de 24:
    # piso de 3 horas); los de 12, 14 y 16 estan en la etapa de 24 horas.
    now = primero.replace(hour=8, minute=30)

    resultados = await asyncio.gather(
        tasks.process_due_appointment_reminders(now=now),
        tasks.process_due_appointment_reminders(now=now),
    )

    assert await _scheduled_reminders(app_sessions) == sorted(
        [
            (turnos["10h"], "2h"),
            (turnos["12h"], "24h"),
            (turnos["14h"], "24h"),
            (turnos["16h"], "24h"),
        ]
    )
    assert sum(int(r["published"]) for r in resultados) == 4

    # Una tercera corrida no duplica los trabajos que siguen pendientes.
    tercera = await tasks.process_due_appointment_reminders(now=now)
    assert tercera["published"] == 0
    assert len(await _scheduled_reminders(app_sessions)) == 4
