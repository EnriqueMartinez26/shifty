"""El superadmin ve en reportes y panel SU tienda, no el consolidado de todas.

2026-09-18, hallazgo B5-02: ``store_scope_for`` devolvia ``None`` para un
``is_global_admin`` y la politica RLS se abre con ese mismo flag, asi que
``/reports/summary``, ``/reports/professionals``, ``/reports/trend``,
``POST /reports/export`` y ``/dashboard/summary`` le entregaban la plata, la
deuda (nombres y saldos de clientes ajenos) y los turnos de TODAS las tiendas
mezcladas.

Decision (OK global del usuario, sugerencia del brief): no hay consolidado.
CLAUDE.md §1: "la consolidacion del panel del dueno espera su ok explicito".
El superadmin ve su propia tienda como cualquier usuario.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from tests.integration.test_aislamiento_multitenant import _montar, _turno
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_aislamiento_por_tienda import (
    _activar,
    _cobrar_manual,
    _fiar,
)


@pytest.mark.asyncio
async def test_el_superadmin_ve_solo_su_tienda_en_reportes_y_panel(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    a = await _montar(client, slug="b502-a", email="b502-a@test.com")
    b = await _montar(client, slug="b502-b", email="b502-b@test.com")
    await _activar(client, a, payments=True, ledger=True)
    await _activar(client, b, payments=True, ledger=True)

    turno_a = await _turno(client, a, hora=10, clave="b502-turno-a-1")
    turno_b = await _turno(client, b, hora=10, clave="b502-turno-b-1")
    await _cobrar_manual(client, b, turno_b)
    await _fiar(client, test_session, b, monto="999.00")

    # El admin de A pasa a ser superadmin. El flag se relee de la base en
    # cada request (regla 1), asi que el mismo token ya viaja como global.
    admin_a = (
        await test_session.execute(select(User).where(User.email == "b502-a@test.com"))
    ).scalar_one()
    admin_a.is_global_admin = True
    await test_session.commit()
    headers = auth_headers(a.token)

    fecha = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
    rango = {"from_date": fecha, "to_date": fecha}

    resumen = await client.get("/reports/summary", params=rango, headers=headers)
    assert resumen.status_code == 200, resumen.text
    cuerpo = resumen.json()
    assert [t["public_id"] for t in cuerpo["appointments"]] == [turno_a]
    assert cuerpo["stats"]["total_revenue"] == 0.0
    assert cuerpo["debt_summary"]["debtors_count"] == 0
    assert cuerpo["debt_summary"]["top_debtors"] == []

    profesionales = await client.get(
        "/reports/professionals", params=rango, headers=headers
    )
    assert profesionales.status_code == 200, profesionales.text
    assert [p["staff_id"] for p in profesionales.json()["professionals"]] == [a.staff]

    tendencia = await client.get(
        "/reports/trend", params={"months": 1}, headers=headers
    )
    assert tendencia.status_code == 200, tendencia.text
    assert sum(p["total_appointments"] for p in tendencia.json()["points"]) <= 1

    export = await client.post(
        "/reports/export",
        headers=headers,
        json={"format": "csv", "from_date": fecha, "to_date": fecha},
    )
    assert export.status_code == 200, export.text
    assert turno_a in export.text and turno_b not in export.text

    panel = await client.get("/dashboard/summary", headers=headers)
    assert panel.status_code == 200, panel.text
    assert [t["public_id"] for t in panel.json()["upcoming_appointments"]] == [turno_a]
    assert panel.json()["stats"]["pending_confirmations"] == 1
