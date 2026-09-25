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
