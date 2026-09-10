"""Las guardas que viven en Postgres frenan aunque el codigo se equivoque.

Se escribe SQL crudo con el rol dueno (superusuario: salta RLS pero no
triggers ni constraints) para simular un bug o un acceso directo a la base:

- El trigger ``trg_appointment_transition_guard`` rechaza una transicion que
  no esta en el grafo aunque nadie pase por ``apply_status_transition``.
- La exclusion GiST ``ex_appointments_no_active_overlap`` rechaza un segundo
  turno activo que se superponga para el mismo profesional, y deja pasar el
  mismo turno si esta cancelado (el WHERE de la constraint).
"""

from datetime import datetime, timedelta, timezone

import pytest
import ulid
from httpx import AsyncClient
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


async def _turno_pendiente(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str]:
    """Crea un turno por la API (estado pending) y devuelve (public_id, token)."""
    _, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=10, minute=0, second=0, microsecond=0)
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "idempotency_key": f"pg-guarda-{slug}",
        },
    )
    assert alta.status_code == 201, alta.text
    return str(alta.json()["public_id"]), token


@pytest.mark.asyncio
async def test_el_trigger_rechaza_transiciones_fuera_del_grafo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    turno, _ = await _turno_pendiente(client, app_sessions, "trigger")

    # pending -> completed no existe en ALLOWED_STATUS_TRANSITIONS.
    with pytest.raises(IntegrityError, match="Transicion de turno invalida"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("update appointments set status='completed' where id=:pid"),
                {"pid": turno},
            )

    # pending -> confirmed si existe: el trigger no estorba lo legitimo.
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update appointments set status='confirmed' where id=:pid"),
            {"pid": turno},
        )
    async with owner_engine.connect() as conn:
        estado = (
            await conn.execute(
                text("select status from appointments where id=:pid"), {"pid": turno}
            )
        ).scalar_one()
    assert estado == "confirmed"


async def _copiar_turno(
    owner_engine: AsyncEngine, public_id: str, *, minutos: int, status: str
) -> None:
    """Inserta una copia del turno corrida N minutos, saltando la aplicacion."""
    nuevo = str(ulid.ULID())
    async with owner_engine.begin() as conn:
        columnas = [
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_schema='public' and table_name='appointments' "
                        "order by ordinal_position"
                    )
                )
            ).all()
        ]
        reemplazos = {
            "id": ":nuevo",
            "idempotency_key": "NULL",
            "starts_at": f"starts_at + interval '{minutos} minutes'",
            "ends_at": f"ends_at + interval '{minutos} minutes'",
            "status": ":status",
        }
        seleccion = ", ".join(reemplazos.get(c, c) for c in columnas)
        await conn.execute(
            text(
                f"insert into appointments ({', '.join(columnas)}) "
                f"select {seleccion} from appointments where id = :pid"
            ),
            {"nuevo": nuevo, "status": status, "pid": public_id},
        )


@pytest.mark.asyncio
async def test_la_exclusion_gist_frena_la_doble_reserva_aunque_el_codigo_falle(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    turno, _ = await _turno_pendiente(client, app_sessions, "gist")

    # Mismo profesional, 15 minutos despues (se superpone con un turno de 30).
    with pytest.raises(IntegrityError, match="ex_appointments_no_active_overlap"):
        await _copiar_turno(owner_engine, turno, minutos=15, status="pending")

    # Un turno CANCELADO no ocupa el slot: la constraint solo mira activos.
    await _copiar_turno(owner_engine, turno, minutos=15, status="cancelled")

    # Y un turno activo que NO se superpone entra sin problema.
    await _copiar_turno(owner_engine, turno, minutos=30, status="confirmed")
