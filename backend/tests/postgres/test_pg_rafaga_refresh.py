"""Rafaga de ``POST /auth/refresh`` con el MISMO refresh: no cierra todo.

2026-09-28, D-20260928-01. Sintoma: dos pestanas que refrescan a la vez, o una
respuesta de refresh perdida seguida de un reintento, deslogueaban al usuario
en TODOS sus dispositivos. La rotacion revoca la sesion vieja; quien llegaba
segundo (con el token ya revocado, o perdiendo el ``UPDATE ... WHERE revoked_at
IS NULL``) caia en ``_handle_refresh_reuse`` y este corria
``revoke_sessions_for_user``: se llevaba la sesion recien rotada de la pestana
ganadora y las de los otros dispositivos. No habia prueba de rafaga para el
refresh (CLAUDE.md, seccion 4).

Lo que se fija: N refresh concurrentes con la misma cookie dan exactamente un
200 y N-1 401, cero 5xx, una sola sesion viva nueva de esta familia y la
sesion del OTRO dispositivo intacta. Y fuera de la ventana de gracia el reuso
sigue siendo la senal de robo: se revoca todo (regla 15).
"""

from __future__ import annotations

import asyncio
import os
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modules.auth.router import REFRESH_COOKIE
from modules.auth.service import REFRESH_REUSE_GRACE_SECONDS, hash_token
from tests.postgres.conftest import PASSWORD, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA_REFRESH", "10"))


async def _dos_dispositivos(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    *,
    slug: str,
    email: str,
) -> tuple[str, str]:
    """Refresh de la familia bajo prueba y refresh de OTRO dispositivo."""
    await register_and_login(client, sessions, slug=slug, email=email)
    familia = client.cookies.get(REFRESH_COOKIE)
    otro = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert otro.status_code == 200, otro.text
    otro_refresh = client.cookies.get(REFRESH_COOKIE)
    assert familia and otro_refresh and familia != otro_refresh
    # Cada request lleva su cookie explicita: el jar compartido no debe decidir.
    client.cookies.clear()
    return familia, otro_refresh


async def _refresh(client: AsyncClient, token: str) -> int:
    respuesta = await client.post(
        "/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={token}"}
    )
    return respuesta.status_code


async def _vivas(owner_engine: AsyncEngine, email: str) -> set[str]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select s.refresh_token_hash from auth_sessions s "
                "join users u on u.id = s.user_id "
                "where u.email = :email and s.revoked_at is null"
            ),
            {"email": email},
        )
        return {cast(str, fila[0]) for fila in filas.all()}


@pytest.mark.asyncio
async def test_la_rafaga_de_refresh_rota_una_vez_y_no_cierra_los_otros_dispositivos(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    email = "pg-rafaga-refresh@demo.com"
    familia, otro = await _dos_dispositivos(
        client, app_sessions, slug="pg-rafaga-refresh", email=email
    )

    codigos = sorted(
        await asyncio.gather(*(_refresh(client, familia) for _ in range(RAFAGA)))
    )

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    assert codigos.count(401) == RAFAGA - 1, codigos
    vivas = await _vivas(owner_engine, email)
    # La del otro dispositivo sigue viva y de esta familia queda UNA sola: la
    # nueva que emitio la ganadora (la vieja esta revocada por rotacion).
    assert hash_token(otro) in vivas, "la rafaga cerro la sesion de otro dispositivo"
    assert hash_token(familia) not in vivas
    assert len(vivas) == 2, vivas


@pytest.mark.asyncio
async def test_el_reuso_fuera_de_la_ventana_de_gracia_revoca_todo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    email = "pg-reuso-tardio@demo.com"
    familia, otro = await _dos_dispositivos(
        client, app_sessions, slug="pg-reuso-tardio", email=email
    )
    assert await _refresh(client, familia) == 200

    # Se simula el paso del tiempo corriendo hacia atras la revocacion.
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "update auth_sessions "
                "set revoked_at = revoked_at - make_interval(secs => :atras) "
                "where refresh_token_hash = :hash"
            ),
            {"atras": REFRESH_REUSE_GRACE_SECONDS + 5, "hash": hash_token(familia)},
        )

    assert await _refresh(client, familia) == 401
    assert await _vivas(owner_engine, email) == set(), (
        "el reuso de un refresh rotado hace rato no revoco la familia entera"
    )
    assert await _refresh(client, otro) == 401
