"""El horizonte publico tambien para la disponibilidad anonima.

2026-09-25, revision de perf/f4-back.

- ``GET /appointments/availability`` sin token es disponibilidad publica por
  otra puerta (motivos de bloqueo ocultos, mismas claves de cache que
  ``/public/availability``) pero no aplicaba el horizonte de F1-11
  ([-1, +120] dias locales): un anonimo podia pedir cualquier fecha y cada una
  es una clave de cache. Ahora es 422 fuera del horizonte, igual que la
  publica. Con token (el panel) no cambia.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from core.utils import BOOKING_HORIZON_DAYS, today_local
from tests.integration.test_caracterizacion_alta_publica import _redis, _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


def _dia(dias: int) -> str:
    return (today_local() + timedelta(days=dias)).isoformat()


@pytest.mark.asyncio
async def test_disponibilidad_anonima_con_el_horizonte_publico(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "horiz-anonima")

    for dias, esperado in (
        (-2, 422),
        (BOOKING_HORIZON_DAYS + 1, 422),
        (-1, 200),
        (BOOKING_HORIZON_DAYS, 200),
    ):
        res = await client.get(
            "/appointments/availability",
            params={"service_id": t.service, "date": _dia(dias)},
        )
        assert res.status_code == esperado, (dias, res.text[:200])

    # El panel (con token) sigue sin horizonte de producto.
    panel = await client.get(
        "/appointments/availability",
        params={"service_id": t.service, "date": _dia(BOOKING_HORIZON_DAYS + 30)},
        headers=auth_headers(t.token),
    )
    assert panel.status_code == 200, panel.text


@pytest.mark.asyncio
async def test_la_anonima_y_la_publica_comparten_las_claves_de_cache(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "horiz-claves")
    redis: Any = await _redis()
    dia = t.slot.date().isoformat()

    anonima = await client.get(
        "/appointments/availability", params={"service_id": t.service, "date": dia}
    )
    assert anonima.status_code == 200, anonima.text
    claves = {k for k in redis.store if k.startswith("availability:")}
    publica = await client.get(
        "/public/availability",
        params={"store_public_id": t.store, "service_id": t.service, "date": dia},
    )
    assert publica.status_code == 200, publica.text

    assert publica.json() == anonima.json()
    nuevas = {k for k in redis.store if k.startswith("availability:")} - claves
    assert nuevas == set(), nuevas
