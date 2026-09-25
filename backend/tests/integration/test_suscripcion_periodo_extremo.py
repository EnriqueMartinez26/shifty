"""Suscripcion con un fin de periodo absurdo: 422 al cargarla, no 500 despues.

2026-09-24, revision de perf/f4-back. Sintoma: el superadmin podia asignar
una suscripcion con ``current_period_end`` = 9999-12-31. El alta respondia 200,
pero desde ahi el banner del panel (``GET /stores/me/subscription``) y la
corrida diaria de suscripciones calculan ``fin + dias de gracia`` y
desbordaban (``OverflowError``, 500): el dueno quedaba con el panel roto por
un dato que cargo otro.

Decision: el inicio y el fin del periodo caen entre hace 5 anios y dentro de
5 anios (un plan anual, con holgura para contratos largos); fuera de eso,
422 al cargarla.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.billing.model import Plan
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_superadmin_listado_de_tiendas import (
    _token_de_admin_global,
)


@pytest.mark.asyncio
async def test_fin_de_periodo_absurdo_422_y_el_banner_sigue_andando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    soporte = auth_headers(
        await _token_de_admin_global(
            client, test_session, slug="sub-soporte", email="sub-soporte@t.com"
        )
    )
    tienda, token = await register_and_login(
        client, slug="sub-extremo", email="sub-extremo@t.com"
    )
    plan = Plan(name="Plan Extremo", price=1000, currency="ARS")
    test_session.add(plan)
    await test_session.commit()
    ahora = datetime.now(timezone.utc)

    for inicio, fin in (
        (ahora.isoformat(), "9999-12-31T23:59:00+00:00"),
        (ahora.isoformat(), (ahora + timedelta(days=6 * 365)).isoformat()),
        ("0001-01-01T00:00:00+00:00", ahora.isoformat()),
    ):
        res = await client.post(
            f"/superadmin/stores/{tienda}/subscription",
            headers=soporte,
            json={
                "plan_id": plan.id,
                "current_period_start": inicio,
                "current_period_end": fin,
            },
        )
        assert res.status_code == 422, (inicio, fin, res.text)

    banner = await client.get("/stores/me/subscription", headers=auth_headers(token))
    assert banner.status_code == 200, banner.text

    anual = await client.post(
        f"/superadmin/stores/{tienda}/subscription",
        headers=soporte,
        json={
            "plan_id": plan.id,
            "current_period_start": ahora.isoformat(),
            "current_period_end": (ahora + timedelta(days=365)).isoformat(),
        },
    )
    assert anual.status_code == 200, anual.text
