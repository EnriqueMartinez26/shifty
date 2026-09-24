"""F1-13 (plan de rendimiento, R7-02 / R1-03): el solapamiento tiene dos cotas.

2026-09-24. Sintoma: toda consulta de solapamiento era
``starts_at < fin AND ends_at > inicio``. Con un indice que empieza por
``starts_at`` eso solo acota por ARRIBA: la consulta recorria TODA la historia
del profesional, tambien bajo el ``FOR UPDATE`` del alta. La exclusion GiST no
sirve para leer bajo RLS (``&&`` no es leakproof) y varias consultas ni
siquiera filtraban por ``store_id`` (una de ``waitlist/offers.py`` decia
tenerlo y no lo tenia), asi que tampoco llegaban a los indices compuestos.

Ahora cada consulta lleva ``store_id`` y la cota inferior
``starts_at > inicio - MAX_APPOINTMENT_SPAN``, que es correcta porque la base
garantiza ``ends_at <= starts_at + 1 dia`` (``ck_appointments_max_span``). Los
bloqueos pueden durar hasta 366 dias: para ellos la cota inferior es
``end_time > inicio`` sobre ``ix_appointment_blocks_store_staff_end``.

Se capturan las sentencias REALES de cada camino (alta del panel con su
sugerencia, alta publica con "cualquier profesional", agenda del dia, alta de
bloqueos y el cupo liberado de la lista de espera) y se explican como
``shifty_app``. Antes se siembra historia (turnos activos y bloqueos de los
ultimos anos, y bloqueos futuros de OTRA tienda) y se corre ``ANALYZE``: con
las tablas vacias el planner elige cualquier indice que tenga ``staff_id`` (el
GiST incluido) y el plan no dice nada de las cotas.

Decision de indice para bloqueos (EXPLAIN, 2026-09-24): el indice plano
``ix_appointment_blocks_end_time`` ya da la cota ``end_time > inicio``, pero de
TODAS las tiendas: con los bloqueos futuros de otra tienda sembrados el plan
los recorre y los filtra uno por uno. ``ix_appointment_blocks_store_staff_end``
acota por tienda, profesional y fin, y es el que el planner elige.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.appointments.availability import AvailabilityService
from modules.waitlist.offers import ReleasedSlot, slot_still_free
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.planes import (
    Sentencia,
    condiciones_de_indice,
    plan_de,
    resumen,
    sentencias_capturadas,
)

pytestmark = pytest.mark.postgres


def _consultas_de_solapamiento(
    capturadas: list[Sentencia],
) -> tuple[list[Sentencia], list[Sentencia]]:
    turnos = [
        s
        for s in capturadas
        if "FROM appointments" in s[0] and "appointments.ends_at >" in s[0]
    ]
    bloqueos = [
        s
        for s in capturadas
        if "FROM appointment_blocks" in s[0] and "appointment_blocks.end_time >" in s[0]
    ]
    return turnos, bloqueos


async def _sembrar_historia(
    owner_engine: AsyncEngine,
    store: str,
    service: str,
    staff_ids: list[str],
    *,
    otra_tienda: str,
    otro_staff: str,
) -> None:
    """Tres anos de turnos activos y bloqueos pasados por profesional, y un
    ano de bloqueos futuros de otra tienda."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "insert into appointment_blocks (id, store_id, staff_id, "
                "start_time, end_time, reason, is_active, created_at, updated_at) "
                "select 'AJENO' || lpad(g::text, 20, '0'), :store, :staff, "
                "now() + g * interval '4 hours', "
                "now() + g * interval '4 hours' + interval '1 hour', "
                "'Ajeno', true, now(), now() "
                "from generate_series(1, 2000) g"
            ),
            {"store": otra_tienda, "staff": otro_staff},
        )
        service_id = (
            await conn.execute(
                text("select id from services where public_id = :p"), {"p": service}
            )
        ).scalar_one()
        for indice, staff_id in enumerate(staff_ids):
            await conn.execute(
                text(
                    "insert into appointments (id, store_id, staff_id, service_id, "
                    "client_name, starts_at, duration_minutes, status, version, "
                    "created_at, updated_at) "
                    "select 'HIST' || :i || lpad(g::text, 20, '0'), :store, :staff, "
                    ":service, 'Historia', "
                    "date_trunc('hour', now()) - interval '7 days' - g * interval '8 hours', "
                    "30, 'confirmed', 1, now(), now() "
                    "from generate_series(1, 3000) g"
                ),
                {
                    "i": str(indice),
                    "store": store,
                    "staff": staff_id,
                    "service": service_id,
                },
            )
            await conn.execute(
                text(
                    "insert into appointment_blocks (id, store_id, staff_id, "
                    "start_time, end_time, reason, is_active, created_at, updated_at) "
                    "select 'HIST' || :i || lpad(g::text, 20, '0'), :store, :staff, "
                    "now() - interval '7 days' - g * interval '2 days', "
                    "now() - interval '7 days' - g * interval '2 days' + interval '1 hour', "
                    "'Historia', true, now(), now() "
                    "from generate_series(1, 500) g"
                ),
                {"i": str(indice), "store": store, "staff": staff_id},
            )
        await conn.execute(text("analyze appointments"))
        await conn.execute(text("analyze appointment_blocks"))


def _cota_inferior_de_turnos(condicion: str) -> bool:
    return all(
        pieza in condicion for pieza in ("store_id", "starts_at >", "starts_at <")
    )


@pytest.mark.asyncio
async def test_cada_consulta_de_solapamiento_acota_por_tienda_y_por_los_dos_lados(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="pg-cotas", email="pg-cotas@demo.com"
    )
    service = await create_service(client, token)
    uno = await create_staff(client, token, service, email="pro-cotas-1@demo.com")
    dos = await create_staff(client, token, service, email="pro-cotas-2@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    for staff in (uno, dos):
        await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    otra_tienda, otro_token = await register_and_login(
        client, app_sessions, slug="pg-cotas-otra", email="pg-cotas-otra@demo.com"
    )
    otro_staff = await create_staff(
        client,
        otro_token,
        await create_service(client, otro_token),
        email="pro-cotas-otra@demo.com",
    )
    await _sembrar_historia(
        owner_engine,
        store,
        service,
        [uno, dos],
        otra_tienda=otra_tienda,
        otro_staff=otro_staff,
    )

    with sentencias_capturadas(app_engine) as capturadas:
        # Panel: alta (lock + bloqueo + choque) y el choque con su sugerencia.
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(token),
            json={
                "service_id": service,
                "staff_id": uno,
                "starts_at": slot.isoformat(),
                "idempotency_key": "pg-cotas-panel-1",
            },
        )
        assert alta.status_code == 201, alta.text
        choque = await client.post(
            "/appointments/",
            headers=auth_headers(token),
            json={
                "service_id": service,
                "staff_id": uno,
                "starts_at": slot.isoformat(),
                "idempotency_key": "pg-cotas-panel-2",
            },
        )
        assert choque.status_code == 409, choque.text
        # Publico con "cualquier profesional": lectura en lote de los dos.
        publica = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "starts_at": slot.isoformat(),
                "client_name": "Cotas",
                "client_phone": "+5491155500001",
                "idempotency_key": "pg-cotas-publica-1",
            },
        )
        assert publica.status_code == 201, publica.text
        # Alta de bloqueos: turnos del rango con FOR UPDATE.
        bloqueo = await client.post(
            "/appointment-blocks/",
            headers=auth_headers(token),
            json={
                "staff_id": dos,
                "starts_at": (slot + timedelta(hours=3)).isoformat(),
                "ends_at": (slot + timedelta(hours=4)).isoformat(),
                "reason": "Cotas",
            },
        )
        assert bloqueo.status_code == 201, bloqueo.text

        async with app_sessions() as session:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(session)
                # Agenda del dia (disponibilidad), sin pasar por el cache.
                await AvailabilityService(session, None)._load_day(  # type: ignore[arg-type]
                    store, [uno, dos], slot.date()
                )
                # Cupo liberado de la lista de espera (corre con bypass).
                await slot_still_free(
                    session,
                    ReleasedSlot(
                        store_id=store,
                        staff_id=uno,
                        starts_at=slot + timedelta(hours=1),
                        ends_at=slot + timedelta(hours=1, minutes=30),
                    ),
                )
            finally:
                set_tenant_context(None, False)

    turnos, bloqueos = _consultas_de_solapamiento(capturadas)
    assert len({sql for sql, _ in turnos}) >= 6, [sql for sql, _ in turnos]
    assert len({sql for sql, _ in bloqueos}) >= 4, [sql for sql, _ in bloqueos]

    for sentencia in turnos:
        plan = await plan_de(app_engine, sentencia, store_id=store)
        condiciones = [
            cond
            for indice, cond in condiciones_de_indice(plan).items()
            if indice.startswith("ix_appointments")
        ]
        assert any(_cota_inferior_de_turnos(c) for c in condiciones), (
            f"{sentencia[0]}\n{resumen(plan)}"
        )

    for sentencia in bloqueos:
        plan = await plan_de(app_engine, sentencia, store_id=store)
        condicion = condiciones_de_indice(plan).get(
            "ix_appointment_blocks_store_staff_end", ""
        )
        assert "store_id" in condicion and "end_time >" in condicion, (
            f"{sentencia[0]}\n{resumen(plan)}"
        )


@pytest.mark.asyncio
async def test_la_base_rechaza_un_turno_de_mas_de_un_dia(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """La cota inferior es correcta solo si ningun turno dura mas de un dia."""
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-tope-turno", email="pg-tope-turno@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-tope@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": "pg-tope-turno-1",
        },
    )
    assert alta.status_code == 201, alta.text

    async with owner_engine.connect() as conn:
        validada = (
            await conn.execute(
                text(
                    "select convalidated from pg_constraint "
                    "where conname = 'ck_appointments_max_span'"
                )
            )
        ).scalar_one()
    assert validada is True

    # El trigger de ends_at lo recalcula desde duration_minutes: se estira la
    # duracion, que es lo que un bug o un acceso directo podria hacer.
    with pytest.raises(IntegrityError, match="ck_appointments_max_span"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "update appointments set duration_minutes = 1441, "
                    "ends_at = starts_at + interval '1441 minutes' where id = :id"
                ),
                {"id": alta.json()["public_id"]},
            )
