"""AUD2-B6-01 (2026-09-20), correcciones del v-diff.

Dos huecos que dejo la correccion original al filtrar los servicios en el
JOIN de la carga:

(a) El ``selectinload`` filtrado perdio el predicado ``store_id``. CLAUDE.md
    §2 no permite quitar ninguno de los 38 filtros de tienda: son defensa en
    profundidad sobre RLS, no redundancia. Una fila de ``staff_services``
    apuntando al servicio de OTRA tienda -por un bug de escritura o una carga
    directa- se colaba en la ficha del profesional.

(b) ``PATCH /staff/{id}/services`` es la lista EXPLICITA del dueno, pero la
    coleccion filtrada ya no carga las asignaciones a servicios inactivos, asi
    que SQLAlchemy no las podia borrar: el PATCH respondia 200 y la fila
    sobrevivia; al reactivar el servicio volvia a aparecer en la ficha, sin
    que nadie lo pidiera. Ahora el repositorio borra dirigido sobre
    ``staff_services`` los ids que no estan en la lista nueva.

La reversion del borrado logico (AUD2-B6-02) se conserva igual: lo que NO
puede pasar es que una LECTURA borre. Un PATCH explicito si.
"""

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.staff_service import StaffServiceModel
from modules.services.model import Service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _crear_servicio(client: AsyncClient, token: str, nombre: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": 30, "price": 1500},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _crear_profesional(
    client: AsyncClient, token: str, slug: str, service_ids: list[str]
) -> str:
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro Demo",
            "first_name": "Pro",
            "last_name": "Demo",
            "email": f"pro-{slug}@example.com",
            "service_ids": service_ids,
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


@pytest.mark.asyncio
async def test_el_patch_de_servicios_saca_tambien_la_asignacion_inactiva(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    slug = "aud2-b6-01b-patch"
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@example.com")
    vivo = await _crear_servicio(client, token, "Corte")
    borrado = await _crear_servicio(client, token, "Color")
    staff_id = await _crear_profesional(client, token, slug, [vivo, borrado])
    assert (
        await client.delete(f"/services/{borrado}", headers=auth_headers(token))
    ).status_code == 204

    patch = await client.patch(
        f"/staff/{staff_id}/services", headers=auth_headers(token), json=[vivo]
    )
    assert patch.status_code == 200, patch.text

    total = await test_session.execute(
        select(func.count()).select_from(StaffServiceModel)
    )
    assert total.scalar_one() == 1, "la asignacion al servicio inactivo sigue ahi"

    reactivar = await client.patch(
        f"/services/{borrado}", headers=auth_headers(token), json={"is_active": True}
    )
    assert reactivar.status_code == 200, reactivar.text
    ficha = await client.get(f"/staff/{staff_id}", headers=auth_headers(token))
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["service_ids"] == [vivo], (
        "reactivar un servicio no puede devolverselo a quien el dueno se lo saco"
    )


@pytest.mark.asyncio
async def test_el_patch_vacio_deja_al_profesional_sin_ningun_servicio(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    slug = "aud2-b6-01b-vacio"
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@example.com")
    vivo = await _crear_servicio(client, token, "Corte")
    borrado = await _crear_servicio(client, token, "Color")
    staff_id = await _crear_profesional(client, token, slug, [vivo, borrado])
    assert (
        await client.delete(f"/services/{borrado}", headers=auth_headers(token))
    ).status_code == 204

    patch = await client.patch(
        f"/staff/{staff_id}/services", headers=auth_headers(token), json=[]
    )
    assert patch.status_code == 200, patch.text
    total = await test_session.execute(
        select(func.count()).select_from(StaffServiceModel)
    )
    assert total.scalar_one() == 0


@pytest.mark.asyncio
async def test_la_ficha_no_muestra_el_servicio_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Defensa en profundidad: el filtro ``store_id`` de la carga (CLAUDE.md §2)."""
    _, token_a = await register_and_login(
        client, slug="aud2-b6-01b-a", email="aud2-b6-01b-a@example.com"
    )
    _, token_b = await register_and_login(
        client, slug="aud2-b6-01b-b", email="aud2-b6-01b-b@example.com"
    )
    propio = await _crear_servicio(client, token_a, "Corte")
    ajeno = await _crear_servicio(client, token_b, "Ajeno")
    staff_id = await _crear_profesional(client, token_a, "aud2-b6-01b-a", [propio])

    ajeno_id = (
        await test_session.execute(select(Service.id).where(Service.public_id == ajeno))
    ).scalar_one()
    # Fila cruzada, como la dejaria un bug de escritura o una carga directa.
    test_session.add(
        StaffServiceModel(staff_id=staff_id, service_id=str(ajeno_id), rating=None)
    )
    await test_session.commit()

    ficha = await client.get(f"/staff/{staff_id}", headers=auth_headers(token_a))
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["service_ids"] == [propio], (
        "la carga tiene que filtrar por tienda, no solo por is_active"
    )

    listado = await client.get("/staff/", headers=auth_headers(token_a))
    assert listado.status_code == 200, listado.text
    assert ajeno not in listado.text
