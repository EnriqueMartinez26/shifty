"""Horizontes de reserva: una fecha lejana es 422, nunca 500.

2026-09-24, revision de perf/f4-back. Sintoma: un ``starts_at`` como
9999-12-31T23:59Z hacia desbordar ``starts_at + duracion`` (``OverflowError``,
500 por el handler generico) en la reserva publica, en la reprogramacion del
panel y del cliente, y en la reserva desde la lista de espera. Cada camino
toma el horizonte que ya le corresponde:

- Portal (reservar y reprogramar): ``BOOKING_HORIZON_DAYS`` (120 dias
  locales), el mismo de la disponibilidad publica: nadie podia elegir un slot
  mas alla, asi que no cambia el producto.
- Panel, reprogramar: ``PANEL_SELF_BOOKING_MAX_AHEAD`` (2 anios), como el
  auto-turno.
- Lista de espera, reservar desde el panel: las reglas del alta del panel
  para un cliente (FF-04): hasta 5 minutos en el pasado y el horizonte del
  portal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)

LEJANO = "9999-12-31T23:59:00+00:00"


def _en(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()


@pytest.mark.asyncio
async def test_reserva_publica_mas_alla_del_horizonte_422(client: AsyncClient) -> None:
    t = await _tienda(client, "horiz-publica")

    for i, cuando in enumerate((LEJANO, _en(122))):
        res = await client.post(
            "/public/appointments",
            json=_reserva(t, f"horiz-publica-{i:04d}", starts_at=cuando),
        )
        assert res.status_code == 422, (cuando, res.text)


@pytest.mark.asyncio
async def test_reprogramar_desde_el_panel_mas_alla_de_dos_anios_422(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "horiz-panel")
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.token),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.slot.isoformat(),
            "idempotency_key": "horiz-panel-alta",
        },
    )
    assert alta.status_code == 201, alta.text

    for i, cuando in enumerate((LEJANO, _en(731))):
        res = await client.patch(
            f"/appointments/{alta.json()['public_id']}/reschedule",
            headers=auth_headers(t.token),
            json={"new_starts_at": cuando, "idempotency_key": f"horiz-panel-rs-{i}"},
        )
        assert res.status_code == 422, (cuando, res.text)
