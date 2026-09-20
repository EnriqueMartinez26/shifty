"""``GET /ops/slo``: quien lo ve, con que alcance y que id expone.

2026-09-20, hallazgo AUD2-B5-19: el endpoint no aparecia en un solo test
(``grep "/ops/slo" tests/`` -> nada) y devolvia ``"store_id": user.store_id``,
que es el id INTERNO de la tienda (el ULID de ``stores.id``), no el
``public_id`` que expone el resto de la API. Filtrar ids internos es la forma
de que empiecen a usarse desde afuera, y un endpoint de permisos sin test es
el candidato natural a que un refactor lo abra de mas.

Ademas el alcance global del superadmin es lo contrario de la decision B5-02
(reportes y panel: el superadmin ve SU tienda). Es razonable para una metrica
de infraestructura —los webhooks y el outbox son de la plataforma, no de una
tienda— pero no estaba escrito en ningun lado. Queda afirmado aca y en el
docstring del endpoint.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

CAMPOS = {
    "scope",
    "store_id",
    "status",
    "checked_at",
    "metrics",
    "thresholds",
    "alerts",
}


@pytest.mark.asyncio
async def test_el_admin_ve_su_tienda_y_nunca_el_id_interno(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="aud2b519", email="aud2b519@test.com"
    )
    tienda = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    assert tienda.id != tienda.public_id, "la semilla no distingue los dos ids"

    res = await client.get("/ops/slo", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert set(cuerpo) == CAMPOS
    assert cuerpo["scope"] == "store"
    assert cuerpo["store_id"] == store_public_id
    assert tienda.id not in res.text, "se filtro el id interno de la tienda"
    assert set(cuerpo["metrics"]) == {
        "pending_webhooks",
        "failed_webhooks",
        "pending_outbox",
    }
    assert cuerpo["status"] == "ok"
    assert cuerpo["alerts"] == []


@pytest.mark.asyncio
async def test_el_profesional_no_ve_el_slo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="aud2b519-pro", email="aud2b519-pro@test.com"
    )
    # El rol se relee de la base en cada request (regla 1).
    usuario = (
        await test_session.execute(
            select(User).where(User.email == "aud2b519-pro@test.com")
        )
    ).scalar_one()
    usuario.role = UserRole.STAFF
    await test_session.commit()

    res = await client.get("/ops/slo", headers=auth_headers(token))
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_el_superadmin_ve_el_consolidado_de_la_plataforma(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Excepcion DELIBERADA a B5-02: el SLO es de infraestructura."""
    _, token = await register_and_login(
        client, slug="aud2b519-sa", email="aud2b519-sa@test.com"
    )
    usuario = (
        await test_session.execute(
            select(User).where(User.email == "aud2b519-sa@test.com")
        )
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()

    res = await client.get("/ops/slo", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["scope"] == "global"
    assert cuerpo["store_id"] is None
