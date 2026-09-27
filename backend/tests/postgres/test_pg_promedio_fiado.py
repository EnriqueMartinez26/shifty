"""Promedio del fiado contra Postgres real: AVG sobre numeric (S-03).

2026-09-18, seguimiento S-03 de la revision de B2-06: ``get_ledger_summary``
calcula ``average_balance`` con ``func.avg`` en SQL. En SQLite eso devuelve
``float``; en Postgres, ``numeric`` con 16+ decimales. El router lo fija con
``Decimal(str(avg)).quantize(Decimal("0.01"), ROUND_HALF_EVEN)``, pero la
suite de integracion solo lo probaba en SQLite. Aca se verifica en Postgres
que el valor expuesto por la API coincide, a 2 decimales y con la misma regla
de redondeo, con el calculado a mano en Decimal:

- una division periodica (100 + 100 + 50.01) / 3 = 83.3366... -> "83.34";
- un empate exacto en el tercer decimal (0.01 + 0.04) / 2 = 0.025 -> "0.02"
  (half-even; con half-up seria "0.03"), que es donde numeric y float
  podrian divergir si el casteo pasara por float.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _clientes(
    client: AsyncClient, token: str, store: str, slug: str, cuantos: int
) -> list[str]:
    """``cuantos`` clientes distintos de la tienda, nacidos de reservas publicas."""
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reservas: list[str] = []
    for i in range(cuantos):
        res = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911777{i:05d}",
                "accepts_terms": True,
                "idempotency_key": f"{slug}-{i:04d}",
            },
        )
        assert res.status_code == 201, res.text
        reservas.append(cast(str, res.json()["public_id"]))
    busqueda = await client.get(
        "/appointments/search?page=1&page_size=50", headers=auth_headers(token)
    )
    assert busqueda.status_code == 200, busqueda.text
    por_turno = {i["public_id"]: i["client_id"] for i in busqueda.json()["results"]}
    return [cast(str, por_turno[r]) for r in reservas]


async def _resumen_con_saldos(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    slug: str,
    saldos: list[str],
) -> dict[str, object]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert flags.status_code == 200, flags.text
    clientes = await _clientes(client, token, store, slug, len(saldos))
    for cliente, saldo in zip(clientes, saldos, strict=True):
        cargo = await client.post(
            f"/ledger/customers/{cliente}/movements",
            headers=auth_headers(token),
            json={"movement_type": "charge", "amount": saldo},
        )
        assert cargo.status_code == 200, cargo.text
    resumen = await client.get("/ledger/summary", headers=auth_headers(token))
    assert resumen.status_code == 200, resumen.text
    return cast(dict[str, object], resumen.json())


def _esperado(saldos: list[str]) -> str:
    valores = [Decimal(s) for s in saldos]
    promedio = sum(valores, Decimal("0")) / len(valores)
    return str(promedio.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "saldos"),
    [
        ("pg-avg-periodico", ["100.00", "100.00", "50.01"]),
        ("pg-avg-empate", ["0.01", "0.04"]),
    ],
)
async def test_el_promedio_del_fiado_coincide_con_el_calculo_en_decimal(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    slug: str,
    saldos: list[str],
) -> None:
    resumen = await _resumen_con_saldos(client, app_sessions, slug, saldos)

    assert resumen["debtors_count"] == len(saldos)
    assert resumen["average_balance"] == _esperado(saldos), resumen
    total = sum((Decimal(s) for s in saldos), Decimal("0"))
    assert resumen["total_balance"] == str(total.quantize(Decimal("0.01")))
