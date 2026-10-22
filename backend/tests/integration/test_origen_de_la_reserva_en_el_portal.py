"""El portal marca sus reservas con ``booked_via = "portal"`` (antiabuso, S5).

2026-10-22. La columna nace con ``panel`` por defecto y la limpieza de la
tienda (``GET /appointments/recent-portal``) lista solo las del portal: sin
esta marca una reserva publica quedaba como del panel y no aparecia para
cancelarla. Reprogramar desde "Mis turnos" crea un turno nuevo; conserva el
origen del original.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_caracterizacion_autogestion import (
    TELEFONO,
    _con_turno,
    _turno,
)


@pytest.mark.asyncio
async def test_la_reserva_publica_queda_marcada_como_del_portal(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, turno = await _con_turno(client, monkeypatch, "origen-portal")

    assert (await _turno(test_session, turno)).booked_via == "portal"


@pytest.mark.asyncio
async def test_la_limpieza_de_la_tienda_ve_la_reserva_hecha_en_el_portal(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "origen-limpieza")

    res = await client.get(
        "/appointments/recent-portal",
        params={"hours": 24},
        headers=auth_headers(t.token),
    )

    assert res.status_code == 200, res.text
    assert [fila["public_id"] for fila in res.json()["items"]] == [turno]


@pytest.mark.asyncio
async def test_reprogramar_desde_mis_turnos_conserva_el_origen(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "origen-reprograma")

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "origen-reprograma-0001",
        },
    )

    assert res.status_code == 200, res.text
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.booked_via == "portal"
