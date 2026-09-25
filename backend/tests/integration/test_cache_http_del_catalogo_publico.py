"""Cache HTTP del catalogo publico (F1-29, R10-03 / R10-04, decision 11).

2026-09-24: todos los GET publicos salian ``no-store`` y cada visita al
portal repetia la cascada tienda -> servicios -> profesionales contra la
base. Servicios y profesionales pasan a ``public, max-age=0, s-maxage=30,
stale-while-revalidate=30``: el navegador revalida siempre (``max-age=0``) y
el edge (nginx ``proxy_cache``) sirve la copia hasta 30 s, y 30 s mas
mientras la renueva. Un cambio del catalogo tarda hasta 60 s en verse.

La vitrina de la tienda (``/public/stores/{slug}``) queda ``no-store``
(decision 11): lleva la suspension, la politica de sena que el cliente
acepta y los flags, que no pueden quedar viejos. Tambien disponibilidad,
previews, OTP y autogestion.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
    register_and_login,
)

CATALOGO = "public, max-age=0, s-maxage=30, stale-while-revalidate=30"


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    servicio = await create_service(client, token)
    await create_staff(client, token, servicio, email=f"pro-{slug}@example.com")
    return store_public_id, servicio


@pytest.mark.asyncio
@pytest.mark.parametrize("ruta", ["/public/services", "/public/staff"])
async def test_servicios_y_profesionales_se_cachean_en_el_edge(
    client: AsyncClient, ruta: str
) -> None:
    store_public_id, _ = await _tienda(client, f"cat-{ruta.rsplit('/', 1)[-1]}")
    res = await client.get(ruta, params={"store_public_id": store_public_id})
    assert res.status_code == 200, res.text
    assert res.json()
    assert res.headers["cache-control"] == CATALOGO
    assert "pragma" not in res.headers


@pytest.mark.asyncio
async def test_profesionales_por_servicio_tambien(client: AsyncClient) -> None:
    _, servicio = await _tienda(client, "cat-staff-servicio")
    res = await client.get("/public/staff", params={"service_id": servicio})
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == CATALOGO


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ruta", "params"),
    [
        ("/public/services", {"store_public_id": "01JNOEXISTE0000000000000000"}),
        ("/public/staff", {"store_public_id": "01JNOEXISTE0000000000000000"}),
        ("/public/staff", {}),
    ],
    ids=["servicios-404", "staff-404", "staff-422"],
)
async def test_un_error_del_catalogo_no_se_cachea(
    client: AsyncClient, ruta: str, params: dict[str, str]
) -> None:
    res = await client.get(ruta, params=params)
    assert res.status_code >= 400
    assert res.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_la_vitrina_y_la_disponibilidad_siguen_sin_cache(
    client: AsyncClient,
) -> None:
    store_public_id, servicio = await _tienda(client, "cat-vitrina")
    vitrina = await client.get("/public/stores/cat-vitrina")
    assert vitrina.status_code == 200, vitrina.text
    assert vitrina.headers["cache-control"] == "no-store"
    assert vitrina.headers["pragma"] == "no-cache"

    disponibilidad = await client.get(
        "/public/availability",
        params={"service_id": servicio, "date": "2030-01-07"},
    )
    assert disponibilidad.headers["cache-control"] == "no-store"
