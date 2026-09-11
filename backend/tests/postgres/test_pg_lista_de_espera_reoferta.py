"""Dos corridas solapadas del beat no re-ofrecen el mismo cupo dos veces.

``expire_lapsed_offers`` toma las ofertas vencidas con ``FOR UPDATE SKIP
LOCKED``. En SQLite esto es una mentira (no hay concurrencia ni locks de
fila): solo Postgres real prueba que la segunda corrida no vuelve a ofrecer
el hueco que la primera ya esta pasando a la siguiente persona.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import expire_lapsed_offers
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import register_and_login

pytestmark = pytest.mark.postgres


async def _dos_en_espera_con_oferta_vencida(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> str:
    """Deja una oferta vencida sobre un cupo libre y otra persona esperando."""
    store, token = await register_and_login(
        client, sessions, slug="reoferta", email="reoferta@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-reoferta@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=15, minute=0, second=0, microsecond=0)

    for indice, (nombre, telefono) in enumerate(
        [("Primera", "+5491155550301"), ("Segunda", "+5491155550302")]
    ):
        alta = await client.post(
            "/public/waitlist",
            json={
                "store_public_id": store,
                "service_id": service,
                "window_starts_at": (slot - timedelta(hours=2)).isoformat(),
                "window_ends_at": (slot + timedelta(hours=2)).isoformat(),
                "client_name": nombre,
                "client_phone": telefono,
                "client_email": f"espera{indice}@demo.com",
            },
        )
        assert alta.status_code == 201, alta.text

    # La primera ya recibio una oferta que acaba de vencer, sobre un cupo que
    # sigue libre: es el estado exacto que mira el job.
    vencida = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            primera = (
                (
                    await session.execute(
                        select(WaitlistEntry).order_by(WaitlistEntry.created_at.asc())
                    )
                )
                .scalars()
                .first()
            )
            assert primera is not None
            await session.execute(
                text(
                    "UPDATE waitlist_entries SET status='offered', notified_at=:v, "
                    "offer_expires_at=:v, offered_staff_id=:staff, "
                    "offered_starts_at=:inicio, offered_ends_at=:fin WHERE id=:id"
                ),
                {
                    "v": vencida,
                    "staff": staff,
                    "inicio": slot,
                    "fin": slot + timedelta(minutes=30),
                    "id": primera.id,
                },
            )
            await session.commit()
        finally:
            set_tenant_context(None, False)
    return store


@pytest.mark.asyncio
async def test_dos_corridas_solapadas_reofrecen_el_cupo_una_sola_vez(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    await _dos_en_espera_con_oferta_vencida(client, app_sessions)
    ahora = datetime.now(timezone.utc)
    ambas_leyeron = asyncio.Barrier(2)

    async def corrida() -> int:
        """Una corrida del beat que NO commitea hasta que la otra tambien leyo.

        Sin la barrera las dos se serializan solas (la primera commitea antes
        de que la segunda consulte) y la carrera no se reproduce nunca.
        """
        async with app_sessions() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                resultado = await expire_lapsed_offers(db, now=ahora)
                await ambas_leyeron.wait()
                await db.commit()
                return resultado.reoffered
            finally:
                set_tenant_context(None, False)

    reofertas = await asyncio.gather(corrida(), corrida())

    assert sum(reofertas) == 1, f"el mismo cupo se re-ofrecio dos veces: {reofertas}"

    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            filas = (
                await session.execute(
                    select(WaitlistEntry.client_name, WaitlistEntry.status).order_by(
                        WaitlistEntry.created_at.asc()
                    )
                )
            ).all()
            estados = {str(nombre): str(estado) for nombre, estado in filas}
        finally:
            set_tenant_context(None, False)
    assert estados == {"Primera": "waiting", "Segunda": "offered"}
