"""F3-05 (plan de rendimiento, R2-06): las cohortes no recorren la historia.

2026-09-24. ``_client_cohorts`` agrupaba por cliente todos los turnos de la
tienda con ``starts_at < fin`` (sin cota inferior): el plan era un recorrido
del indice ``(store_id, starts_at)`` desde el primer turno de la historia. Con
anos de turnos, el resumen de 7 dias del Dashboard rozaba el
``statement_timeout``.

Ahora cada acceso a ``appointments`` de la sentencia de cohortes esta acotado:
o por el rango (``starts_at >= inicio AND starts_at < fin``) o por UN cliente
(``client_id = ...``, la sonda de ``EXISTS``/``NOT EXISTS``). Se siembran tres
anos de historia, se corre ``ANALYZE`` y se explica la sentencia REAL como
``shifty_app``, bajo RLS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.planes import (
    nodos,
    plan_de,
    resumen,
    sentencias_capturadas,
)

pytestmark = pytest.mark.postgres


async def sembrar_historia(
    owner_engine: AsyncEngine,
    store: str,
    service: str,
    staff: str,
    *,
    prefijo: str = "",
) -> None:
    """300 clientes, tres anos de turnos (6000) y 30 en la ultima semana.

    ``prefijo`` separa los ids y emails cuando se siembra mas de una tienda.
    """
    async with owner_engine.begin() as conn:
        service_id = (
            await conn.execute(
                text("select id from services where public_id = :p"), {"p": service}
            )
        ).scalar_one()
        await conn.execute(
            text(
                "insert into users (id, email, hashed_password, first_name, "
                "last_name, role, store_id, is_global_admin, is_active, "
                "created_at, updated_at) "
                "select :p || 'CLI' || lpad(g::text, 23, '0'), "
                ":p || 'cli' || g || '@historia.test', 'x', 'Cliente', g::text, "
                "'client', :store, false, true, now(), now() "
                "from generate_series(1, 300) g"
            ),
            {"store": store, "p": prefijo},
        )
        await conn.execute(
            text(
                "insert into appointments (id, store_id, staff_id, service_id, "
                "client_id, client_name, starts_at, ends_at, duration_minutes, "
                "status, version, created_at, updated_at) "
                "select :p || 'HIST' || lpad(g::text, 22, '0'), :store, :staff, "
                ":service, :p || 'CLI' || lpad((g % 300 + 1)::text, 23, '0'), "
                "'Historia', "
                "now() - interval '10 days' - g * interval '4 hours', "
                "now() - interval '10 days' - g * interval '4 hours' "
                "+ interval '30 minutes', 30, 'completed', 1, now(), now() "
                "from generate_series(1, 6000) g"
            ),
            {"store": store, "staff": staff, "service": service_id, "p": prefijo},
        )
        await conn.execute(
            text(
                "insert into appointments (id, store_id, staff_id, service_id, "
                "client_id, client_name, starts_at, ends_at, duration_minutes, "
                "status, version, created_at, updated_at) "
                "select :p || 'RANGO' || lpad(g::text, 21, '0'), :store, :staff, "
                ":service, :p || 'CLI' || lpad((g * 7 % 300 + 1)::text, 23, '0'), "
                "'Rango', now() - g * interval '5 hours', "
                "now() - g * interval '5 hours' + interval '30 minutes', 30, "
                "'completed', 1, now(), now() "
                "from generate_series(1, 30) g"
            ),
            {"store": store, "staff": staff, "service": service_id, "p": prefijo},
        )
        await conn.execute(text("analyze appointments"))
        await conn.execute(text("analyze users"))


def accesos_a_turnos(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Nodos que recorren un indice de ``appointments`` (con o sin alias)."""
    return [
        nodo
        for nodo in nodos(plan)
        if str(nodo.get("Index Name", "")).startswith(
            ("ix_appointments", "appointments_")
        )
    ]


def escaneos_de_turnos(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        nodo
        for nodo in nodos(plan)
        if nodo.get("Node Type") == "Seq Scan"
        and nodo.get("Relation Name") == "appointments"
    ]


def acotado(nodo: dict[str, Any]) -> bool:
    """Por el rango (las dos cotas de ``starts_at``) o por UN cliente."""
    condicion = str(nodo.get("Index Cond", ""))
    por_rango = "starts_at >=" in condicion and "starts_at <" in condicion
    return por_rango or "client_id" in condicion


@pytest.mark.asyncio
async def test_las_cohortes_leen_el_rango_y_sondean_por_cliente(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="pg-cohortes", email="pg-cohortes@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-coh@demo.com")
    await sembrar_historia(owner_engine, store, service, staff)
    hoy = datetime.now(timezone.utc).date()
    rango = {
        "from_date": (hoy - timedelta(days=7)).isoformat(),
        "to_date": hoy.isoformat(),
    }

    with sentencias_capturadas(app_engine) as capturadas:
        res = await client.get(
            "/reports/summary", params=rango, headers=auth_headers(token)
        )
    assert res.status_code == 200, res.text
    cohortes = res.json()["client_stats"]
    assert cohortes["total_clients"] > 0
    assert cohortes["inactive_clients"] > 0

    # La de cohortes es la unica sentencia del resumen que lee turnos y
    # clientes sin tocar pagos ni cortar con LIMIT (antes y despues de F3-05).
    candidatas = [
        s
        for s in capturadas
        if "appointments" in s[0]
        and "users" in s[0]
        and "payments" not in s[0]
        and "LIMIT" not in s[0]
    ]
    assert len(candidatas) == 1, [s[0] for s in capturadas]
    plan = await plan_de(app_engine, candidatas[0], store_id=store)
    turnos = accesos_a_turnos(plan)
    assert turnos, resumen(plan)
    assert escaneos_de_turnos(plan) == [], resumen(plan)
    sueltos = [nodo for nodo in turnos if not acotado(nodo)]
    assert sueltos == [], (
        "acceso a appointments sin cota de rango ni de cliente "
        f"(recorre la historia):\n{resumen(plan)}"
    )
    # Y el rango entra por un indice de starts_at con las dos cotas (el
    # planner elige entre (store_id, starts_at) y starts_at segun cuantas
    # tiendas haya; los dos acotan la lectura al rango).
    por_rango = [
        nodo
        for nodo in turnos
        if "starts_at >=" in str(nodo.get("Index Cond", ""))
        and "starts_at <" in str(nodo.get("Index Cond", ""))
    ]
    assert por_rango, resumen(plan)
