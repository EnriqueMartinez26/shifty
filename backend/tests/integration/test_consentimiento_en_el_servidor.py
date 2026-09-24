"""La reserva publica exige el consentimiento en el servidor.

2026-09-24, PV-09: ``accepts_terms`` era opcional (``False`` por defecto) y
solo el checkbox del front lo exigia. Un POST directo a
``/public/appointments`` reservaba sin aceptar los terminos de Shifty ni la
politica de sena de la tienda, y el turno quedaba sin ``terms_accepted_at``:
sin respaldo del consentimiento justo en el caso que lo necesita (reclamo por
una sena retenida). Ahora falta el consentimiento -> 422 y el turno siempre
nace con la marca. No hay columna de version de terminos (la agrega, si hace
falta, la fase de migraciones): se registra solo el instante.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


async def _cuerpo(client: AsyncClient, slug: str) -> dict[str, Any]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return {
        "store_public_id": store,
        "service_id": servicio,
        "staff_id": staff,
        "starts_at": dia.replace(
            hour=10, minute=0, second=0, microsecond=0
        ).isoformat(),
        "client_name": "Cliente Consentimiento",
        "client_phone": "+5491155590909",
        "accepts_terms": True,
    }


async def _turnos(test_session: AsyncSession) -> int:
    return int(
        (
            await test_session.execute(select(func.count()).select_from(Appointment))
        ).scalar_one()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("consentimiento", [None, False])
async def test_sin_aceptar_los_terminos_no_se_reserva(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    consentimiento: bool | None,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cuerpo = await _cuerpo(client, f"pv09-sin-{consentimiento}".lower())
    if consentimiento is None:
        del cuerpo["accepts_terms"]
    else:
        cuerpo["accepts_terms"] = consentimiento

    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == 422, res.text
    assert await _turnos(test_session) == 0


@pytest.mark.asyncio
async def test_con_los_terminos_aceptados_el_turno_guarda_el_instante(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cuerpo = await _cuerpo(client, "pv09-con")
    antes = datetime.now(timezone.utc)

    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == 201, res.text
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == res.json()["public_id"])
        )
    ).scalar_one()
    assert turno.terms_accepted_at is not None
    aceptado = turno.terms_accepted_at
    if aceptado.tzinfo is None:
        aceptado = aceptado.replace(tzinfo=timezone.utc)
    assert aceptado >= antes - timedelta(seconds=1)
