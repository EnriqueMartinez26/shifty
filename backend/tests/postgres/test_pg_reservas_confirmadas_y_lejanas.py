"""Rafagas sobre el alta publica con las decisiones de Mateo del 2026-10-20.

A) Una reserva sin cobro nace ``confirmed`` y sin ``expires_at``: cambio el
   estado con el que el alta inserta el turno, asi que se vuelve a probar la
   rafaga contra Postgres real (lock del profesional + exclusion GiST, que
   cubre ``confirmed`` igual que ``pending``): N sobre el mismo horario dejan
   UNA, N identicas crean UNA, cero 5xx y un solo aviso al dueno.

B) Una reserva lejana con sena obligatoria y WhatsApp elegido se rechaza con
   422 antes de escribir: una rafaga no deja ninguna fila.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


async def _tienda(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    slug: str,
    *,
    dias: int,
    **servicio: Any,
) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"whatsapp_number": "11 5555 0303"},
    )
    assert res.status_code == 200, res.text
    service = await create_service(client, token, **servicio)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=dias)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        store,
        service,
        staff,
        dia.replace(hour=11, minute=0, second=0, microsecond=0),
    )


def _reserva(
    store: str, service: str, staff: str, slot: datetime, i: int, key: str
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911566{i:05d}",
        "client_email": f"c54911566{i:05d}@example.com",
        "payment_method": "manual",
        "accepts_terms": True,
        "idempotency_key": key,
    }


async def _escalar(owner_engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with owner_engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


async def _activos_del_staff(owner_engine: AsyncEngine, staff: str) -> list[Any]:
    async with owner_engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        # El id publico del profesional es su id.
                        "select status, expires_at from appointments "
                        "where staff_id = :staff "
                        "and status in ('pending','pending_payment','confirmed')"
                    ),
                    {"staff": staff},
                )
            ).all()
        )


async def _avisos_de_reserva(owner_engine: AsyncEngine, store: str) -> int:
    return cast(
        int,
        await _escalar(
            owner_engine,
            "select count(*) from outbox_messages o join stores s on s.id = o.store_id "
            "where s.public_id = :store and o.event_type = 'appointment.booked_online'",
            store=store,
        ),
    )


@pytest.mark.asyncio
async def test_rafaga_mismo_slot_sin_sena_deja_un_confirmado(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, service, staff, slot = await _tienda(
        client, app_sessions, "conf-rafaga", dias=5
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, i, f"conf-rafaga-{i:02d}"),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert codigos.count(409) == RAFAGA - 1, codigos
    [ganadora] = [r for r in respuestas if r.status_code == 201]
    assert ganadora.json()["status"] == "confirmed"
    activos = await _activos_del_staff(owner_engine, staff)
    assert [(estado, vence) for estado, vence in activos] == [("confirmed", None)]
    # Un solo aviso al dueno: los rechazados no dejaron nada en el outbox.
    assert await _avisos_de_reserva(owner_engine, store) == 1


@pytest.mark.asyncio
async def test_rafaga_identica_sin_sena_crea_un_solo_confirmado(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, service, staff, slot = await _tienda(
        client, app_sessions, "conf-idem", dias=5
    )
    cuerpo = _reserva(store, service, staff, slot, 1, "conf-idem-misma-clave")

    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo) for _ in range(RAFAGA))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 201}
    assert len(creados) == 1, codigos
    activos = await _activos_del_staff(owner_engine, staff)
    assert [estado for estado, _vence in activos] == ["confirmed"]
    assert await _avisos_de_reserva(owner_engine, store) == 1


@pytest.mark.asyncio
async def test_rafaga_lejana_por_whatsapp_no_deja_ninguna_fila(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # 46 dias: lejano; la tienda tiene solo WhatsApp (sin MP usable).
    store, service, staff, slot = await _tienda(
        client,
        app_sessions,
        "lejos-rafaga",
        dias=46,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, i, f"lejos-rafaga-{i:02d}"),
            )
            for i in range(RAFAGA)
        )
    )

    assert {r.status_code for r in respuestas} == {422}
    assert {r.json()["error_code"] for r in respuestas} == {"FAR_BOOKING_UNAVAILABLE"}
    assert await _activos_del_staff(owner_engine, staff) == []
    pagos = await _escalar(
        owner_engine,
        "select count(*) from payments p join stores s on s.id = p.store_id "
        "where s.public_id = :store",
        store=store,
    )
    clientes = await _escalar(
        owner_engine,
        "select count(*) from users u join stores s on s.id = u.store_id "
        "where s.public_id = :store and u.role = 'client'",
        store=store,
    )
    assert (pagos, clientes) == (0, 0)
