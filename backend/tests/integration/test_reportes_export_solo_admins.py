"""Exportar el reporte es de admins: el profesional ve el suyo pero no exporta.

2026-09-18, hallazgo B5-06: ``POST /reports/export`` autorizaba con
``REPORT_VIEWERS`` (el mismo helper que ``/summary``), que incluye al
profesional; ``REPORT_EXPORTERS = {super_admin, store_admin}`` estaba definido
en ``core/roles.py`` y no lo usaba nadie. No habia un solo test de
``/reports/export``.

Decision (OK global del usuario, sugerencia del brief): el profesional NO
exporta; el endpoint usa ``REPORT_EXPORTERS`` tal cual. Sigue pudiendo VER su
propio reporte (``REPORT_VIEWERS``).
"""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

CUERPO = {"format": "csv", "from_date": "2026-09-01", "to_date": "2026-09-10"}


async def _como(test_session: AsyncSession, email: str, role: UserRole) -> None:
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.role = role
    await test_session.commit()


@pytest.mark.asyncio
async def test_el_profesional_ve_su_reporte_pero_no_lo_exporta(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="b506-pro", email="b506-pro@test.com"
    )
    # El rol se relee de la base en cada request (regla 1).
    await _como(test_session, "b506-pro@test.com", UserRole.STAFF)
    headers = auth_headers(token)

    export = await client.post("/reports/export", headers=headers, json=CUERPO)
    assert export.status_code == 403, export.text

    resumen = await client.get(
        "/reports/summary",
        headers=headers,
        params={"from_date": CUERPO["from_date"], "to_date": CUERPO["to_date"]},
    )
    assert resumen.status_code == 200, resumen.text


@pytest.mark.asyncio
async def test_el_admin_de_la_tienda_exporta(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="b506-admin", email="b506-admin@test.com"
    )
    export = await client.post(
        "/reports/export", headers=auth_headers(token), json=CUERPO
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("text/csv")
    assert date(2026, 9, 1).isoformat() in export.headers["content-disposition"]
