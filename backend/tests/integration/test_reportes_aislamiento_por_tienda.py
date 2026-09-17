"""Reports y dashboard acotan por tienda en el codigo, no solo por RLS.

2026-09-17, hallazgo B5-01: ninguna consulta de ``modules/reports`` ni de
``modules/dashboard`` llevaba un predicado ``store_id``; el aislamiento entre
tiendas quedaba 100% en la politica RLS de Postgres. La suite corre en SQLite,
donde el contexto de tenant no se aplica (``core/database.py``), asi que si
manana alguien rompia la politica ningun test lo veia: sin los filtros, la
tienda B recibia en ``/reports/summary`` los turnos, la plata cobrada y los
deudores de la tienda A, en ``/reports/professionals`` al personal ajeno y en
``/dashboard/summary`` los pendientes y proximos turnos de la otra tienda.

CLAUDE.md §2: RLS es la garantia y los filtros ``store_id`` en las consultas
son la defensa en profundidad; no se quita ninguno de los dos. Este test es la
evidencia de la segunda capa, que es la unica que SQLite puede ejercitar.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_aislamiento_multitenant import (
    Tienda,
    _montar,
    _turno,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


async def _activar(client: AsyncClient, tienda: Tienda, **flags: bool) -> None:
    res = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(tienda.token), json=flags
    )
    assert res.status_code == 200, res.text


async def _cobrar_manual(client: AsyncClient, tienda: Tienda, turno: str) -> None:
    res = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(tienda.token),
        json={},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "manual_confirmed"


async def _fiar(
    client: AsyncClient, test_session: AsyncSession, tienda: Tienda, *, monto: str
) -> None:
    """Deja a un cliente de ``tienda`` debiendo ``monto`` en el fiado."""
    store = (
        await test_session.execute(select(Store).where(Store.public_id == tienda.store))
    ).scalar_one()
    deudor = User(
        email=f"deudor-{store.slug}@b501.test",
        hashed_password="no-se-loguea",
        first_name="Deudor",
        last_name=store.slug,
        role=UserRole.CLIENT,
        store_id=store.id,
    )
    test_session.add(deudor)
    await test_session.commit()
    res = await client.post(
        f"/ledger/customers/{deudor.id}/movements",
        headers=auth_headers(tienda.token),
        json={"movement_type": "charge", "amount": monto},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_reports_y_dashboard_solo_muestran_la_tienda_propia(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Dos tiendas con datos: cada una ve solo lo suyo en los tres endpoints.

    La tienda A queda con dos turnos (uno cobrado), un profesional y un deudor;
    la tienda B con un turno sin cobrar y sin fiado. Se verifica a B contra la
    contaminacion de A y a A contra el vaciado (el riesgo declarado del filtro:
    que un dato armado sin ``store_id`` consistente empiece a devolver vacio).
    """
    a = await _montar(client, slug="rep-aisl-a", email="rep-aisl-a@test.com")
    b = await _montar(client, slug="rep-aisl-b", email="rep-aisl-b@test.com")
    await _activar(client, a, payments=True, ledger=True)

    turno_a_cobrado = await _turno(client, a, hora=10, clave="rep-aisl-a-1")
    turno_a_pendiente = await _turno(client, a, hora=11, clave="rep-aisl-a-2")
    turno_b = await _turno(client, b, hora=10, clave="rep-aisl-b-1")
    await _cobrar_manual(client, a, turno_a_cobrado)
    await _fiar(client, test_session, a, monto="250.00")

    fecha = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
    rango = {"from_date": fecha, "to_date": fecha}

    # --- La tienda B no ve nada de A -------------------------------------
    resumen_b = await client.get(
        "/reports/summary", params=rango, headers=auth_headers(b.token)
    )
    assert resumen_b.status_code == 200, resumen_b.text
    cuerpo_b = resumen_b.json()
    assert [t["public_id"] for t in cuerpo_b["appointments"]] == [turno_b]
    assert cuerpo_b["stats"]["total_appointments"] == 1
    assert cuerpo_b["stats"]["total_revenue"] == 0.0
    assert cuerpo_b["debt_summary"]["debtors_count"] == 0
    assert cuerpo_b["debt_summary"]["outstanding_balance"] == 0.0
    assert cuerpo_b["debt_summary"]["top_debtors"] == []
    assert [s["revenue"] for s in cuerpo_b["top_services"]] == [0.0]

    profesionales_b = await client.get(
        "/reports/professionals", params=rango, headers=auth_headers(b.token)
    )
    assert profesionales_b.status_code == 200, profesionales_b.text
    assert [p["staff_id"] for p in profesionales_b.json()["professionals"]] == [b.staff]

    panel_b = await client.get("/dashboard/summary", headers=auth_headers(b.token))
    assert panel_b.status_code == 200, panel_b.text
    assert panel_b.json()["stats"]["pending_confirmations"] == 1
    assert [t["public_id"] for t in panel_b.json()["upcoming_appointments"]] == [
        turno_b
    ]

    # --- La tienda A sigue viendo todo lo suyo ---------------------------
    resumen_a = await client.get(
        "/reports/summary", params=rango, headers=auth_headers(a.token)
    )
    assert resumen_a.status_code == 200, resumen_a.text
    cuerpo_a = resumen_a.json()
    assert sorted(t["public_id"] for t in cuerpo_a["appointments"]) == sorted(
        [turno_a_cobrado, turno_a_pendiente]
    )
    assert cuerpo_a["stats"]["total_revenue"] == 10000.0
    assert cuerpo_a["debt_summary"]["debtors_count"] == 1
    assert cuerpo_a["debt_summary"]["outstanding_balance"] == 250.0

    profesionales_a = await client.get(
        "/reports/professionals", params=rango, headers=auth_headers(a.token)
    )
    assert profesionales_a.status_code == 200, profesionales_a.text
    assert [p["staff_id"] for p in profesionales_a.json()["professionals"]] == [a.staff]
    assert profesionales_a.json()["professionals"][0]["revenue"] == 10000.0

    panel_a = await client.get("/dashboard/summary", headers=auth_headers(a.token))
    assert panel_a.status_code == 200, panel_a.text
    assert panel_a.json()["stats"]["pending_confirmations"] == 1
    assert sorted(
        t["public_id"] for t in panel_a.json()["upcoming_appointments"]
    ) == sorted([turno_a_cobrado, turno_a_pendiente])
