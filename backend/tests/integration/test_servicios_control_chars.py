"""B6-01 (2026-09-17): el catalogo de servicios no pasaba por la regla 19.

Sintoma: ``POST /services/`` y ``PATCH /services/{public_id}`` aceptaban en
``name`` y ``description`` los caracteres que ``core/validation.
reject_control_chars`` bloquea en el resto de los textos libres (NUL, bidi
override U+202E, isolate U+2066, zero-width U+200B, BOM). El string se
persistia y salia tal cual en ``PublicServiceResponse`` (pagina publica de
reserva) y en el ``service_name`` de los mails al cliente: la pagina mostraba
un nombre distinto al guardado (Trojan Source).

La guarda se agrega en los schemas de ENTRADA (``ServiceCreate`` y
``ServiceUpdate``) y no en ``ServiceBase``: ``ServiceResponse`` hereda de la
base, asi que un validador ahi rompia la lectura de un servicio ya guardado
con un invisible (500 en GET/list). Leer sigue sin validar; escribir, si.
"""

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

VENENOS = [
    pytest.param("Corte " + chr(0x202E) + "otracosa", id="bidi-override"),
    pytest.param("Cor" + chr(0x200B) + "te", id="zero-width"),
    pytest.param("Cor" + chr(0x2066) + "te", id="bidi-isolate"),
    pytest.param(chr(0xFEFF) + "Corte", id="bom"),
    pytest.param("Cor\x00te", id="nul"),
]


async def _nombres_guardados(session: AsyncSession) -> list[str]:
    session.expire_all()
    filas = (await session.execute(select(Service.name))).scalars().all()
    return [str(nombre) for nombre in filas]


async def _crear_servicio_limpio(client: AsyncClient, token: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": "Corte", "duration_minutes": 30, "price": 1500},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("veneno", VENENOS)
async def test_post_servicio_rechaza_control_chars_en_name(
    client: AsyncClient, test_session: AsyncSession, veneno: str
) -> None:
    _, token = await register_and_login(
        client, slug="b6-01-post", email="b6-01-post@example.com"
    )

    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": veneno, "duration_minutes": 30, "price": 1500},
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "VALIDATION_ERROR"
    assert await _nombres_guardados(test_session) == []


@pytest.mark.asyncio
async def test_post_servicio_rechaza_control_chars_en_description(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="b6-01-desc", email="b6-01-desc@example.com"
    )

    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Corte",
            "description": "Incluye lavado" + chr(0x202E),
            "duration_minutes": 30,
            "price": 1500,
        },
    )

    assert res.status_code == 422, res.text
    assert await _nombres_guardados(test_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("veneno", VENENOS)
async def test_patch_servicio_rechaza_control_chars_en_name(
    client: AsyncClient, test_session: AsyncSession, veneno: str
) -> None:
    _, token = await register_and_login(
        client, slug="b6-01-patch", email="b6-01-patch@example.com"
    )
    public_id = await _crear_servicio_limpio(client, token)

    res = await client.patch(
        f"/services/{public_id}",
        headers=auth_headers(token),
        json={"name": veneno},
    )

    assert res.status_code == 422, res.text
    assert await _nombres_guardados(test_session) == ["Corte"]


@pytest.mark.asyncio
async def test_patch_servicio_rechaza_control_chars_en_description(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="b6-01-patch-desc", email="b6-01-patch-desc@example.com"
    )
    public_id = await _crear_servicio_limpio(client, token)

    res = await client.patch(
        f"/services/{public_id}",
        headers=auth_headers(token),
        json={"description": "Con\x00lavado"},
    )

    assert res.status_code == 422, res.text
    test_session.expire_all()
    fila = (
        await test_session.execute(
            select(Service).where(Service.public_id == public_id)
        )
    ).scalar_one()
    assert fila.description is None


@pytest.mark.asyncio
async def test_servicio_con_texto_normal_sigue_entrando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Acentos, enie y saltos de linea legitimos no son control chars."""
    _, token = await register_and_login(
        client, slug="b6-01-ok", email="b6-01-ok@example.com"
    )

    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Corte Clásico & Peinado",
            "description": "Incluye lavado.\nDuración aproximada: 30 minutos.",
            "duration_minutes": 30,
            "price": 1500,
        },
    )
    assert res.status_code == 201, res.text
    public_id = cast(str, res.json()["public_id"])

    upd = await client.patch(
        f"/services/{public_id}",
        headers=auth_headers(token),
        json={"name": "Corte Señor", "description": "Con toalla caliente"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Corte Señor"
    assert await _nombres_guardados(test_session) == ["Corte Señor"]


@pytest.mark.asyncio
async def test_servicio_legado_con_invisible_se_sigue_leyendo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Contrato de salida intacto: la guarda es de entrada, no de lectura.

    Un servicio guardado antes de B6-01 con un zero-width en el nombre no
    puede dejar al panel sin catalogo (500 en GET/list); se lee igual y falla
    recien al intentar guardarlo de nuevo sin limpiar.
    """
    store_public_id, token = await register_and_login(
        client, slug="b6-01-legado", email="b6-01-legado@example.com"
    )
    tienda = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    legado = Service(
        store_id=tienda.id,
        name="Cor" + chr(0x200B) + "te legado",
        duration_minutes=30,
        price=1500,
    )
    test_session.add(legado)
    await test_session.flush()
    legado.public_id = legado.id
    await test_session.commit()

    uno = await client.get(f"/services/{legado.public_id}", headers=auth_headers(token))
    assert uno.status_code == 200, uno.text
    assert uno.json()["name"] == legado.name

    todos = await client.get("/services/", headers=auth_headers(token))
    assert todos.status_code == 200, todos.text
    assert [s["name"] for s in todos.json()] == [legado.name]
