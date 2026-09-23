"""Bajo RLS real, tomar el slug de otra tienda es 409: ni 500 ni 200.

AUD2-B3-15, 2026-09-20. ``PATCH /stores/me`` tenia un pre-chequeo
``select(Store).where(Store.slug == slug)`` que corria con el contexto de
tenant del admin. La politica ``stores_rls_policy`` restringe ``stores`` a
``id = current_setting('app.current_store_id')``
(``alembic/versions/d5ec116d06a3_refactor_backend_v2.py``), asi que en Postgres
la consulta no veia el slug de otra tienda: su 400 ``SLUG_ALREADY_IN_USE`` era
inalcanzable y el resultado real era el 409 del ``IntegrityError`` contra
``stores.slug UNIQUE``. En SQLite, donde corre toda la suite de integracion, no
hay RLS y el pre-chequeo si se disparaba, asi que el comportamiento de los dos
motores no coincidia y ningun test lo miraba (§4 de CLAUDE.md).

El pre-chequeo se borro y la garantia quedo donde siempre estuvo: el indice
unico. Este test afirma el camino REAL, con RLS forzada y el rol ``shifty_app``:
- el conflicto sale 409 neutro, no 500 y no un 200 que pise la otra tienda;
- la otra tienda conserva su slug;
- un slug libre se sigue pudiendo tomar.

Nota de ejecucion: escrito junto al arreglo pero NO corrido (el lote no levanta
contenedores). Lo corre el job ``backend-postgres`` de CI.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.stores.model import Store
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

OCUPADO = "b315-pg-ocupado"
PROPIO = "b315-pg-propio"


async def _slugs(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    """Lee las dos tiendas con contexto de superadmin (RLS las esconderia)."""
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            filas = (
                (await session.execute(select(Store.slug).order_by(Store.slug)))
                .scalars()
                .all()
            )
            return list(filas)
        finally:
            set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_tomar_el_slug_de_otra_tienda_sale_409_y_no_pisa_nada(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    await register_and_login(
        client, app_sessions, slug=OCUPADO, email=f"{OCUPADO}@demo.com"
    )
    _store, token = await register_and_login(
        client, app_sessions, slug=PROPIO, email=f"{PROPIO}@demo.com"
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"slug": OCUPADO}
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT", res.text

    assert sorted(await _slugs(app_sessions)) == sorted([OCUPADO, PROPIO]), (
        "el slug de otra tienda quedo pisado o duplicado"
    )


@pytest.mark.asyncio
async def test_un_slug_libre_se_sigue_tomando_bajo_rls(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug=PROPIO, email=f"{PROPIO}@demo.com"
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"slug": "b315-pg-nuevo"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "b315-pg-nuevo"
