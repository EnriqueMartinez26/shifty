"""Dos bloqueos solapados sobre el mismo profesional no rompen la reserva.

Audit B1-02 (2026-09-17). Sintoma: el dueno carga "Vacaciones" y despues
"Feriado" adentro de esas vacaciones, sobre el mismo profesional (el alta de
bloqueos lo permite). A partir de ahi cualquier reserva que caiga en el
solape, publica o desde el panel, respondia 500: la consulta de bloqueos
usaba ``scalar_one_or_none()`` sin ``limit`` y con dos filas levantaba
``MultipleResultsFound``. Tiene que ser 409 (horario bloqueado), como con un
solo bloqueo.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _tienda_con_dos_bloqueos_solapados(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local

    for inicio, fin, motivo in (
        (base, base + timedelta(hours=2), "Vacaciones"),
        (base + timedelta(minutes=30), base + timedelta(hours=1), "Feriado"),
    ):
        bloqueo = await client.post(
            "/appointment-blocks/",
            headers=auth_headers(token),
            json={
                "staff_id": staff,
                "starts_at": inicio.isoformat(),
                "ends_at": fin.isoformat(),
                "reason": motivo,
            },
        )
        assert bloqueo.status_code == 201, bloqueo.text

    # Adentro de los DOS bloqueos a la vez.
    return store, token, service, staff, base + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_reserva_publica_dentro_de_dos_bloqueos_solapados_responde_409(
    client: AsyncClient,
) -> None:
    store, _token, service, staff, slot = await _tienda_con_dos_bloqueos_solapados(
        client, "solape-pub"
    )
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Solape",
            "client_phone": "+5491155550202",
            "accepts_terms": True,
            "idempotency_key": "solape-publico-001",
        },
    )
    assert reserva.status_code == 409, reserva.text


@pytest.mark.asyncio
async def test_reserva_del_panel_dentro_de_dos_bloqueos_solapados_responde_409(
    client: AsyncClient,
) -> None:
    _store, token, service, staff, slot = await _tienda_con_dos_bloqueos_solapados(
        client, "solape-panel"
    )
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "idempotency_key": "solape-panel-001",
        },
    )
    assert reserva.status_code == 409, reserva.text
    assert reserva.status_code < 500
