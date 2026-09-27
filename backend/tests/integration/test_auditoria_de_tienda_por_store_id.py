"""La auditoria de una tienda se filtra en SQL por ``audit_logs.store_id``.

Auditoria B3-11, 2026-09-16 (decision del 2026-09-18). Sintoma:
``list_store_audit_logs`` traia las ``limit*4`` entradas de superadmin mas
recientes de TODAS las tiendas y filtraba en Python. Si en esa ventana no
habia ninguna de esta tienda, el panel mostraba "sin actividad" para una
tienda que si la tenia (regla 11: el filtro va en SQL). Ademas cargaba en
memoria todos los ids de usuarios de la tienda, sin tope.

Ahora cada entrada de superadmin guarda el ``store_id`` de la tienda a la que
pertenece y el listado filtra por esa columna con un ``LIMIT`` real. Planes y
cupones son globales: su ``store_id`` queda NULL a proposito.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditLog
from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]


async def _superadmin(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, dict[str, str]]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    usuario = (
        await test_session.execute(select(User).where(User.email == f"{slug}@test.com"))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    return store_public_id, auth_headers(token)


async def _logs(
    client: AsyncClient, headers: dict[str, str], store_public_id: str, limit: int
) -> list[JsonDict]:
    res = await client.get(
        f"/superadmin/stores/{store_public_id}/audit-logs?limit={limit}",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return cast(list[JsonDict], res.json())


@pytest.mark.asyncio
async def test_la_historia_de_la_tienda_no_se_pierde_detras_de_otras_tiendas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda_pid, headers = await _superadmin(client, test_session, "audit-sa")

    # Un evento de ESTA tienda...
    editar = await client.patch(
        f"/superadmin/stores/{tienda_pid}",
        headers=headers,
        json={"name": "Tienda Auditada"},
    )
    assert editar.status_code == 200, editar.text

    # ...y despues muchos eventos de superadmin ajenos a ella (planes globales
    # y otra tienda), mas que la vieja ventana de limit*4.
    for numero in range(6):
        plan = await client.post(
            "/superadmin/plans",
            headers=headers,
            json={
                "name": f"Plan Ruido {numero}",
                "price": "1000",
                "currency": "ARS",
                "billing_interval": "monthly",
            },
        )
        assert plan.status_code == 201, plan.text

    logs = await _logs(client, headers, tienda_pid, limit=1)
    assert len(logs) == 1, "la tienda aparece sin actividad aunque la tuvo"
    assert logs[0]["resource_type"] == "Store"


@pytest.mark.asyncio
async def test_cada_entrada_de_superadmin_guarda_su_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda_pid, headers = await _superadmin(client, test_session, "audit-cols")
    tienda = (
        await test_session.execute(select(Store).where(Store.public_id == tienda_pid))
    ).scalar_one()

    editar = await client.patch(
        f"/superadmin/stores/{tienda_pid}", headers=headers, json={"name": "Otra"}
    )
    assert editar.status_code == 200, editar.text
    plan = await client.post(
        "/superadmin/plans",
        headers=headers,
        json={
            "name": "Plan Global",
            "price": "1000",
            "currency": "ARS",
            "billing_interval": "monthly",
        },
    )
    assert plan.status_code == 201, plan.text

    filas = (
        await test_session.execute(
            select(AuditLog.resource_type, AuditLog.store_id).where(
                AuditLog.context == "superadmin"
            )
        )
    ).all()
    por_tipo = {tipo: store_id for tipo, store_id in filas}
    assert por_tipo["Store"] == tienda.id
    assert por_tipo["Plan"] is None, "un plan es global: no pertenece a una tienda"

    # Y la otra tienda no ve lo de esta.
    otra_pid, _ = await register_and_login(
        client, slug="audit-otra", email="audit-otra@test.com"
    )
    assert await _logs(client, headers, otra_pid, limit=15) == []
