"""FF-20 / F4-03: buscar clientes en ``GET /users/`` con ``q``.

2026-09-24. Sintoma (revision-funcional-front.md, FF-20; plan F4-03): Fiado y
Usuarios bajaban los primeros 200 usuarios y no habia forma de encontrar al
resto. Contrato (aditivo): ``q`` opcional (2..80 caracteres, sin caracteres de
control) busca por nombre (contiene, sin distinguir mayusculas) o por los
digitos del telefono. Acotado a la tienda del admin; ``limit``/``offset``
como siempre. Sin ``q`` el listado no cambia.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _clientes(
    session: AsyncSession, store_public_id: str, clientes: list[tuple[str, str]]
) -> None:
    store_id = (
        await session.execute(
            select(Store.id).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    for i, (nombre, telefono) in enumerate(clientes):
        session.add(
            User(
                email=f"c{i}-{store_public_id.lower()}@example.com",
                hashed_password=hash_password("x-no-login-123"),
                full_name=nombre,
                phone=telefono,
                role=UserRole.CLIENT,
                store_id=store_id,
            )
        )
    await session.commit()


async def _tienda(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    store, token = await register_and_login(
        client, slug="busca-clientes", email="busca@t.com"
    )
    otra, _ = await register_and_login(client, slug="busca-otra", email="otra@t.com")
    await _clientes(
        session,
        store,
        [
            ("Ana Martinez", "5491155550001"),
            ("Mariana Lopez", "5491155550002"),
            ("Pedro Gomez", "5491166660003"),
            ("100% Real", "5491177770004"),
        ],
    )
    # Mismo nombre en OTRA tienda: nunca aparece.
    await _clientes(session, otra, [("Ana Ajena", "5491155559999")])
    return auth_headers(token)


def _nombres(res: Any) -> list[str]:
    assert res.status_code == 200, res.text
    return sorted(
        f"{u['first_name']} {u['last_name']}"
        for u in cast(list[dict[str, Any]], res.json())
    )


@pytest.mark.asyncio
async def test_busca_por_nombre_sin_distinguir_mayusculas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _tienda(client, test_session)

    res = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "ANA"}
    )

    assert _nombres(res) == ["Ana Martinez", "Mariana Lopez"]


@pytest.mark.asyncio
async def test_busca_por_nombre_y_apellido_juntos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _tienda(client, test_session)

    res = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "ana mart"}
    )

    assert _nombres(res) == ["Ana Martinez"]


@pytest.mark.asyncio
async def test_busca_por_digitos_del_telefono(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _tienda(client, test_session)

    res = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "11 6666"}
    )

    assert _nombres(res) == ["Pedro Gomez"]


@pytest.mark.asyncio
async def test_los_comodines_de_like_son_literales(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _tienda(client, test_session)

    porcentaje = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "0%"}
    )
    guion_bajo = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "__"}
    )

    assert _nombres(porcentaje) == ["100% Real"]
    assert _nombres(guion_bajo) == []


@pytest.mark.asyncio
async def test_sin_q_el_listado_no_cambia(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _tienda(client, test_session)

    res = await client.get("/users/", headers=headers, params={"role": "client"})

    assert _nombres(res) == [
        "100% Real",
        "Ana Martinez",
        "Mariana Lopez",
        "Pedro Gomez",
    ]


@pytest.mark.asyncio
async def test_q_invalido_422(client: AsyncClient, test_session: AsyncSession) -> None:
    headers = await _tienda(client, test_session)

    for q in ("a", "x" * 81, "an\x00a", "an‮a"):
        res = await client.get("/users/", headers=headers, params={"q": q})
        assert res.status_code == 422, (q, res.text)


@pytest.mark.asyncio
async def test_la_barra_invertida_es_literal(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """``\`` es el caracter de escape del LIKE: en ``q`` tiene que buscar una
    barra, no escapar al caracter siguiente ni romper el patron."""
    store, token = await register_and_login(
        client, slug="busca-barra", email="busca-barra@t.com"
    )
    await _clientes(
        test_session,
        store,
        [("Back\Slash", "5491188880001"), ("Backslash Sin", "5491188880002")],
    )
    headers = auth_headers(token)

    barra = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "k\s"}
    )
    barra_y_comodin = await client.get(
        "/users/", headers=headers, params={"role": "client", "q": "\%"}
    )

    assert _nombres(barra) == ["Back\Slash None"]
    assert _nombres(barra_y_comodin) == []
