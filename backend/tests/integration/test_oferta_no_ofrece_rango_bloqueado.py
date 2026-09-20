"""La oferta de lista de espera no manda a nadie a un horario bloqueado.

Auditoria 2, AUD2-B1-08 (2026-09-20). Sintoma: antes de ofrecer un cupo,
`slot_still_free` verificaba que no hubiera un turno activo encima, pero no
que el rango estuviera bloqueado. Secuencia real: un cliente cancela (se
publica `slot_released`), el dueno bloquea esa franja (vacaciones, tramite) y
recien entonces corre el outbox. Al primero de la lista le llegaba "se libero
un turno" con el link, entraba, y el alta le respondia 409 `SCHEDULE_BLOCKED`.
Encima la entrada quedaba `offered` durante `WAITLIST_OFFER_MINUTES` sin que
nadie pudiera usarla y sumaba un `lapsed_offers`, acercando a esa persona al
tope `MAX_LAPSED_OFFERS` por algo que no hizo.

Es el mismo criterio que "un rango liberado no es un turno" (CLAUDE.md, fases
4-7), en el otro sentido: lo que no se puede reservar no se ofrece.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.payments.jobs import process_outbox_batch
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


async def _tienda(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    return store, token, service, staff, slot


async def _anotar(client: AsyncClient, store: str, service: str, slot: datetime) -> str:
    res = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": store,
            "service_id": service,
            "window_starts_at": (slot - timedelta(hours=3)).isoformat(),
            "window_ends_at": (slot + timedelta(hours=3)).isoformat(),
            "client_name": "Lucia Espera",
            "client_phone": "+5491155550101",
            "client_email": "lucia@example.com",
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _reservar_y_cancelar(
    client: AsyncClient,
    token: str,
    store: str,
    service: str,
    staff: str,
    slot: datetime,
) -> None:
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Titular",
            "client_phone": "+5491155550200",
            "client_email": "titular@example.com",
            "idempotency_key": "bloqueo-espera-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    cancel = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/cancel",
        headers=auth_headers(token),
    )
    assert cancel.status_code == 200, cancel.text


async def _entrada(session: AsyncSession, entry_id: str) -> WaitlistEntry:
    session.expire_all()
    return (
        await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_un_bloqueo_sobre_el_cupo_no_dispara_la_oferta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "espera-bloqueo")
    entrada = await _anotar(client, store, service, slot)
    await _reservar_y_cancelar(client, token, store, service, staff, slot)

    # El dueno bloquea la franja ANTES de que el beat procese el evento.
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    mails_antes = len(buzon.enviados)

    resultado = await process_outbox_batch(test_session)

    assert resultado["failed"] == 0
    fila = await _entrada(test_session, entrada)
    assert fila.status == "waiting"
    assert fila.lapsed_offers == 0
    assert fila.offer_expires_at is None
    assert [e for e in buzon.enviados[mails_antes:] if "Se libero" in e[1]] == []


@pytest.mark.asyncio
async def test_un_bloqueo_que_no_solapa_no_frena_la_oferta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda mira el mismo predicado que el alta: bloqueo ACTIVO y que solape."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "espera-sin-bloqueo")
    entrada = await _anotar(client, store, service, slot)
    # Bloqueo pegado al final del cupo: no solapa, no tiene que taparlo.
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": (slot + timedelta(minutes=30)).isoformat(),
            "ends_at": (slot + timedelta(minutes=90)).isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    await _reservar_y_cancelar(client, token, store, service, staff, slot)

    resultado = await process_outbox_batch(test_session)

    assert resultado["failed"] == 0
    assert (await _entrada(test_session, entrada)).status == "offered"
    assert any("Se libero un turno" in e[1] for e in buzon.enviados)
