"""Limpieza de reservas del portal contra Postgres (S5 y S6, 2026-10-22).

Lo que SQLite no prueba (CLAUDE.md §4):

- ``ck_appointments_booked_via`` existe, quedo validado (``733220bbf66e``) y
  la base rechaza un origen que no sea ``portal`` ni ``panel``; el default de
  la columna es ``panel``.
- Rafaga: dos cancelaciones en bloque de los mismos turnos (en orden inverso)
  y la cancelacion de a uno de cada turno, todas a la vez y con una sesion por
  request. Cero 5xx, sin deadlock (el bloque recorre los ids ordenados y
  commitea por turno), y cada turno se cancela UNA vez: un solo
  ``appointment.slot_released``, una sola auditoria de cambio de estado y un
  solo aviso al cliente por turno.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

TURNOS = 3


async def _tienda_con_turnos(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, list[str]]:
    """Tienda con ``TURNOS`` turnos del panel (con email) y su token de admin."""
    _, admin = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    turnos: list[str] = []
    for i in range(TURNOS):
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(admin),
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=9 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911558{i:05d}",
                "client_email": f"cliente-{i}-{slug}@example.com",
                "idempotency_key": f"{slug}-alta-{i:04d}",
            },
        )
        assert alta.status_code == 201, alta.text
        turnos.append(str(alta.json()["public_id"]))
    return admin, turnos


@pytest.mark.asyncio
async def test_el_origen_tiene_default_panel_y_un_check_validado(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _, (turno, *_) = await _tienda_con_turnos(client, app_sessions, "origen-check")

    async with owner_engine.connect() as conn:
        origen = (
            await conn.execute(
                text("SELECT booked_via FROM appointments WHERE id = :id"),
                {"id": turno},
            )
        ).scalar_one()
        validado = (
            await conn.execute(
                text(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = 'ck_appointments_booked_via'"
                )
            )
        ).scalar_one()
        default = (
            await conn.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = 'appointments' AND column_name = 'booked_via'"
                )
            )
        ).scalar_one()
    assert origen == "panel"
    assert validado is True
    assert "panel" in str(default)

    with pytest.raises(IntegrityError, match="ck_appointments_booked_via"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE appointments SET booked_via = 'bot' WHERE id = :id"),
                {"id": turno},
            )


@pytest.mark.asyncio
async def test_rafaga_de_limpiezas_y_cancelaciones_cancela_cada_turno_una_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    admin, turnos = await _tienda_con_turnos(client, app_sessions, "limpieza-rafaga")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE appointments SET booked_via = 'portal' WHERE id = ANY(:ids)"),
            {"ids": turnos},
        )

    llamadas = [
        client.post(
            "/appointments/bulk-cancel",
            headers=auth_headers(admin),
            json={"appointment_ids": turnos, "reason": "Reservas falsas"},
        ),
        client.post(
            "/appointments/bulk-cancel",
            headers=auth_headers(admin),
            json={"appointment_ids": list(reversed(turnos))},
        ),
        *(
            client.patch(f"/appointments/{turno}/cancel", headers=auth_headers(admin))
            for turno in turnos
        ),
    ]
    respuestas: list[Response] = await asyncio.gather(*llamadas)

    assert all(r.status_code < 500 for r in respuestas), [
        r.text[:200] for r in respuestas
    ]
    bloques, sueltas = respuestas[:2], respuestas[2:]
    assert [r.status_code for r in bloques] == [200, 200], [r.text for r in bloques]
    cancelados = Counter(
        turno for r in bloques for turno in r.json()["cancelled"]
    ) + Counter(t for t, r in zip(turnos, sueltas) if r.status_code == 200)
    assert cancelados == Counter(turnos), cancelados
    for r in sueltas:
        if r.status_code != 200:
            assert r.status_code == 409, r.text
            assert r.json()["error_code"] == "APPOINTMENT_ALREADY_CANCELLED"
    for r in bloques:
        assert {s["code"] for s in r.json()["skipped"]} <= {
            "APPOINTMENT_ALREADY_CANCELLED"
        }

    async with owner_engine.connect() as conn:
        estados = (
            await conn.execute(
                text("SELECT status FROM appointments WHERE id = ANY(:ids)"),
                {"ids": turnos},
            )
        ).scalars()
        liberados = (
            await conn.execute(
                text(
                    "SELECT payload->>'appointment_id' FROM outbox_messages "
                    "WHERE event_type = 'appointment.slot_released'"
                )
            )
        ).scalars()
        auditorias = (
            await conn.execute(
                text(
                    "SELECT resource_id FROM audit_logs "
                    "WHERE action = 'status_change' AND resource_id = ANY(:ids)"
                ),
                {"ids": turnos},
            )
        ).scalars()
        avisos = (
            await conn.execute(
                text(
                    "SELECT payload->>'public_id' FROM outbox_messages "
                    "WHERE event_type = 'appointment.cancelled_by_block'"
                )
            )
        ).scalars()
        cancelados_en_bloque = Counter(
            turno for r in bloques for turno in r.json()["cancelled"]
        )
        assert set(estados) == {"cancelled"}
        assert Counter(liberados) == Counter(turnos)
        assert Counter(auditorias) == Counter(turnos)
        # El aviso al cliente sale solo de la limpieza en bloque.
        assert Counter(avisos) == cancelados_en_bloque
