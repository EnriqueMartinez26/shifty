"""Un servicio sin profesional no se publica en el catalogo del portal.

2026-10-08, QA movil (QA\63): un servicio activo sin ningun profesional
asignado salia en ``GET /public/services``; el cliente lo elegia y el portal
le mostraba "No hay turnos disponibles" en todas las fechas, para siempre.
Ahora el catalogo publico solo lista servicios que algun profesional activo
de la tienda puede tomar. El panel los sigue listando (``/services/``) y le
avisa al dueno que no aparecen en su pagina.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _catalogo(client: AsyncClient, store_public_id: str) -> list[str]:
    res = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )
    assert res.status_code == 200, res.text
    return [service["public_id"] for service in res.json()]


@pytest.mark.asyncio
async def test_un_servicio_sin_profesional_no_sale_en_el_catalogo(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="cat-sin-pro", email="cat-sin-pro@example.com"
    )
    sin_profesional = await create_service(client, token)

    assert await _catalogo(client, store_public_id) == []

    # El panel lo sigue mostrando: es el dueno quien lo tiene que asignar.
    panel = await client.get("/services/", headers=auth_headers(token))
    assert sin_profesional in [s["public_id"] for s in panel.json()]


@pytest.mark.asyncio
async def test_al_asignarle_un_profesional_aparece(client: AsyncClient) -> None:
    store_public_id, token = await register_and_login(
        client, slug="cat-con-pro", email="cat-con-pro@example.com"
    )
    servicio = await create_service(client, token)
    otro = await create_service(client, token)
    await create_staff(client, token, servicio, email="pro-cat-con@example.com")

    assert await _catalogo(client, store_public_id) == [servicio]
    assert otro not in await _catalogo(client, store_public_id)


@pytest.mark.asyncio
async def test_un_profesional_inactivo_no_alcanza(client: AsyncClient) -> None:
    store_public_id, token = await register_and_login(
        client, slug="cat-pro-baja", email="cat-pro-baja@example.com"
    )
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email="pro-baja@example.com")

    baja = await client.patch(
        f"/staff/{staff}", headers=auth_headers(token), json={"is_active": False}
    )
    assert baja.status_code == 200, baja.text

    assert await _catalogo(client, store_public_id) == []


@pytest.mark.asyncio
async def test_un_profesional_de_otra_tienda_no_publica_el_servicio(
    client: AsyncClient,
) -> None:
    store_a, token_a = await register_and_login(
        client, slug="cat-tienda-a", email="cat-tienda-a@example.com"
    )
    store_b, token_b = await register_and_login(
        client, slug="cat-tienda-b", email="cat-tienda-b@example.com"
    )
    servicio_a = await create_service(client, token_a)
    servicio_b = await create_service(client, token_b)
    await create_staff(client, token_b, servicio_b, email="pro-tienda-b@example.com")

    assert await _catalogo(client, store_a) == []
    assert await _catalogo(client, store_b) == [servicio_b]
    assert servicio_a not in await _catalogo(client, store_b)
