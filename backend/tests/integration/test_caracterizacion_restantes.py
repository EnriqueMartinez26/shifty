"""Caracterizacion de las ultimas tres funciones largas de B1-12.

Audit B1-12 (2026-09-19), regla 29 de CLAUDE.md:
``PublicRepository.create_appointment`` (87 lineas), ``offer_released_slot``
(87) y el endpoint ``search_appointments`` (83). Antes de partirlas estos
tests fijan lo que devuelven HOY: los mensajes de rechazo del alta, la oferta
de la lista de espera (resultado y mail pendiente, campo por campo) y cada
item de la busqueda. Pasan sobre la base y siguen pasando despues del
refactor sin cambiar una asercion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from core.utils import ensure_utc_aware
from modules.notifications.model import Notification
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import ReleasedSlot, offer_released_slot
from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
)
from tests.integration.test_mails_al_cliente import Buzon


@pytest.mark.asyncio
async def test_alta_mensajes_de_rechazo_del_repositorio(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "carac-repo-alta")
    otro_servicio = await create_service(client, t.token)
    ocupado = await client.post("/public/appointments", json=_reserva(t, "carac-ra-1"))
    assert ocupado.status_code == 201, ocupado.text

    casos: list[tuple[dict[str, Any], str]] = [
        (
            {"service_id": otro_servicio},
            "El profesional no realiza el servicio seleccionado",
        ),
        ({}, "El horario ya esta ocupado. Por favor elegi otro."),
        ({"staff_id": None}, "No hay profesionales disponibles para ese horario"),
    ]
    for i, (extra, mensaje) in enumerate(casos):
        res = await client.post(
            "/public/appointments",
            json=_reserva(
                t,
                f"carac-ra-rechazo-{i}",
                client_phone=f"+54911555590{i:02d}",
                client_email=f"rechazo{i}@example.com",
                **extra,
            ),
        )
        assert res.status_code == 409, res.text
        assert (res.json()["error_code"], res.json()["message"]) == (
            "APPOINTMENT_CONFLICT",
            mensaje,
        )


@pytest.mark.asyncio
async def test_oferta_de_la_lista_de_espera_resultado_y_mail(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "carac-oferta")
    for nombre, telefono, email in (
        ("Primera", "+5491155559101", "primera@example.com"),
        ("Segunda", "+5491155559102", None),
    ):
        alta = await client.post(
            "/public/waitlist",
            json={
                "store_public_id": t.store,
                "service_id": t.service,
                "window_starts_at": (t.slot - timedelta(hours=2)).isoformat(),
                "window_ends_at": (t.slot + timedelta(hours=2)).isoformat(),
                "client_name": nombre,
                "client_phone": telefono,
                **({"client_email": email} if email else {}),
            },
        )
        assert alta.status_code == 201, alta.text
    primera = (
        (
            await test_session.execute(
                select(WaitlistEntry).order_by(WaitlistEntry.created_at.asc())
            )
        )
        .scalars()
        .first()
    )
    assert primera is not None
    primera_id = primera.id
    hueco = ReleasedSlot(
        store_id=primera.store_id,
        staff_id=primera.staff_id or (await _staff_id(test_session, t.staff)),
        starts_at=t.slot,
        ends_at=t.slot + timedelta(minutes=30),
        reason="cancelled",
    )
    ahora = datetime.now(timezone.utc)

    # Dentro de la antelacion: solo se avisa al duenio.
    cerca = await offer_released_slot(
        test_session, hueco, now=t.slot - timedelta(hours=1)
    )
    assert (cerca.candidates, cerca.offered_entry_id, cerca.owner_notified) == (
        2,
        None,
        True,
    )
    assert cerca.pending_email is None
    await test_session.rollback()

    oferta = await offer_released_slot(test_session, hueco, now=ahora)

    assert (oferta.candidates, oferta.offered_entry_id, oferta.owner_notified) == (
        2,
        primera_id,
        True,
    )
    assert oferta.pending_email is not None
    assert oferta.pending_email.email == "primera@example.com"
    detalles = dict(oferta.pending_email.details)
    base = settings.FRONTEND_URL.rstrip("/")
    assert detalles == {
        "public_id": primera_id,
        "client_name": "Primera",
        "service": "Consulta",
        "staff": "Pro Demo",
        "staff_kind": "person",
        "starts_at": t.slot.isoformat(),
        "store_name": "Tienda carac-oferta",
        "store_phone": "",
        "booking_url": f"{base}/b/carac-oferta",
        "offer_url": detalles["offer_url"],
        "offer_minutes": settings.WAITLIST_OFFER_MINUTES,
    }
    assert detalles["offer_url"].startswith(f"{base}/b/carac-oferta?service=")
    assert detalles["offer_url"].endswith(f"&date={t.slot.date().isoformat()}")
    await test_session.flush()
    ofrecida = (
        await test_session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == primera_id)
        )
    ).scalar_one()
    assert ofrecida.status == "offered"
    assert ensure_utc_aware(ofrecida.offered_starts_at) == t.slot  # type: ignore[arg-type]
    assert ensure_utc_aware(ofrecida.offered_ends_at) == (  # type: ignore[arg-type]
        t.slot + timedelta(minutes=30)
    )
    avisos = (await test_session.execute(select(Notification))).scalars().all()
    assert len(avisos) == 1
    assert "2 en lista de espera" in (avisos[0].body or "")
    await test_session.rollback()


async def _staff_id(session: AsyncSession, staff_public_id: str) -> str:
    from modules.staff.model import Staff

    return str(
        (
            await session.execute(select(Staff.id).where(Staff.id == staff_public_id))
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_busqueda_de_turnos_items_y_paginado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "carac-busqueda")
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(t, "carac-busq-1", custom_fields={}),
    )
    assert reserva.status_code == 201, reserva.text

    res = await client.get(
        "/appointments/search",
        headers=auth_headers(t.token),
        params={"client_name": "Caracterizado", "page": 1, "page_size": 5},
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert (cuerpo["total"], cuerpo["page"], cuerpo["page_size"]) == (1, 1, 5)
    item = cuerpo["results"][0]
    assert {k: v for k, v in item.items() if k not in {"starts_at", "ends_at"}} == {
        "public_id": reserva.json()["public_id"],
        "status": "pending",
        "notes": "Primera vez",
        "notes_staff": None,
        "intake_answers": {},
        "cancelled_at": None,
        "completed_at": None,
        "service_name": "Consulta",
        "service_id": t.service,
        "staff_name": "Pro Demo",
        "staff_id": t.staff,
        "client_name": "Cliente Caracterizado",
        "client_id": item["client_id"],
        "client_phone": "5491155558001",
    }
