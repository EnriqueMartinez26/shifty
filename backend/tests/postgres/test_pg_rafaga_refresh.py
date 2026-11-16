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
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modules.auth import service as auth_service
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


async def _rotar(client: AsyncClient, token: str) -> str:
    respuesta = await client.post(
        "/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={token}"}
    )
    assert respuesta.status_code == 200, respuesta.text
    nuevo = respuesta.cookies.get(REFRESH_COOKIE)
    assert nuevo and nuevo != token
    return nuevo


async def _envejecer(owner_engine: AsyncEngine, *tokens: str) -> None:
    async with owner_engine.begin() as conn:
        for token in tokens:
            await conn.execute(
                text(
                    "update auth_sessions "
                    "set revoked_at = revoked_at - make_interval(secs => :atras) "
                    "where refresh_token_hash = :hash"
                ),
                {
                    "atras": REFRESH_REUSE_GRACE_SECONDS + 5,
                    "hash": hash_token(token),
                },
            )


async def _motivos(
    owner_engine: AsyncEngine, primero: str, segundo: str
) -> list[str | None]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select revoked_reason from auth_sessions "
                "where refresh_token_hash in (:primero, :segundo)"
            ),
            {"primero": hash_token(primero), "segundo": hash_token(segundo)},
        )
        return [cast(str | None, fila[0]) for fila in filas.all()]


async def _esperar_bloqueadas(owner_engine: AsyncEngine, esperado: int) -> None:
    """Espera a que Postgres confirme la intercalacion bajo un row lock."""
    # La app tiene lock_timeout de 3 s; observar la barrera antes de que venza.
    limite = asyncio.get_running_loop().time() + 2
    async with owner_engine.connect() as conn:
        while asyncio.get_running_loop().time() < limite:
            bloqueadas = await conn.scalar(
                text(
                    "select count(*) from pg_stat_activity "
                    "where datname = current_database() "
                    "and pid <> pg_backend_pid() "
                    "and cardinality(pg_blocking_pids(pid)) > 0 "
                    "and query ilike '%FOR UPDATE%'"
                )
            )
            if int(bloqueadas or 0) >= esperado:
                return
            # El avance lo determina el estado observable de Postgres; el
            # intervalo solo evita consultar el catálogo en un loop ocupado.
            await asyncio.sleep(0.01)
    raise AssertionError(f"Postgres no mostró {esperado} solicitudes bloqueadas")


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


@pytest.mark.asyncio
async def test_reuso_concurrente_cascadea_una_vez_y_no_toca_login_posterior(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    email = "pg-reuso-repetido@demo.com"
    familia, otro = await _dos_dispositivos(
        client, app_sessions, slug="pg-reuso-repetido", email=email
    )
    assert await _refresh(client, familia) == 200

    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "update auth_sessions "
                "set revoked_at = revoked_at - make_interval(secs => :atras) "
                "where refresh_token_hash = :hash"
            ),
            {"atras": REFRESH_REUSE_GRACE_SECONDS + 5, "hash": hash_token(familia)},
        )

    codigos = await asyncio.gather(*(_refresh(client, familia) for _ in range(RAFAGA)))
    assert all(codigo == 401 for codigo in codigos), codigos
    assert await _vivas(owner_engine, email) == set()

    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    posterior = client.cookies.get(REFRESH_COOKIE)
    assert posterior and posterior not in {familia, otro}

    assert await _refresh(client, familia) == 401
    assert await _refresh(client, posterior) == 200


@pytest.mark.asyncio
async def test_reusos_concurrentes_de_tokens_distintos_consumen_toda_la_historia(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    email = "pg-reuso-distinto@demo.com"
    familia, otro = await _dos_dispositivos(
        client, app_sessions, slug="pg-reuso-distinto", email=email
    )
    viejo_b = await _rotar(client, familia)
    vigente_c = await _rotar(client, viejo_b)
    await _envejecer(owner_engine, familia, viejo_b)

    codigos = await asyncio.gather(
        *(_refresh(client, familia if i % 2 == 0 else viejo_b) for i in range(RAFAGA))
    )
    assert all(codigo == 401 for codigo in codigos), codigos
    assert await _vivas(owner_engine, email) == set()
    motivos = await _motivos(owner_engine, familia, viejo_b)
    assert len(motivos) == 2
    assert {motivo for motivo in motivos if motivo is not None} == {
        "reuse_detected",
        "superseded",
    }

    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    posterior = client.cookies.get(REFRESH_COOKIE)
    assert posterior and posterior not in {familia, viejo_b, vigente_c, otro}

    replays = await asyncio.gather(_refresh(client, familia), _refresh(client, viejo_b))
    assert tuple(replays) == (401, 401), replays
    vivas = await _vivas(owner_engine, email)
    assert vivas == {hash_token(posterior)}, vivas
    assert await _refresh(client, posterior) == 200


@pytest.mark.asyncio
async def test_reuso_y_login_esperan_el_mismo_lock_de_usuario_en_postgres(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "pg-reuso-login-lock@demo.com"
    familia, _otro = await _dos_dispositivos(
        client, app_sessions, slug="pg-reuso-login-lock", email=email
    )
    await _rotar(client, familia)
    await _envejecer(owner_engine, familia)

    async def password_valida(_password: str, _hashed_password: str) -> bool:
        # Aisla el intercalado de locks del coste variable de bcrypt en CI.
        return True

    monkeypatch.setattr(auth_service, "verify_password_async", password_valida)

    tareas: list[asyncio.Task[Any]] = []
    async with owner_engine.connect() as conn:
        transaccion = await conn.begin()
        try:
            await conn.execute(
                text("select id from users where email = :email for update"),
                {"email": email},
            )
            reuso = asyncio.create_task(_refresh(client, familia))
            tareas.append(reuso)
            await _esperar_bloqueadas(owner_engine, 1)

            login = asyncio.create_task(
                client.post("/auth/login", json={"email": email, "password": PASSWORD})
            )
            tareas.append(login)
            await _esperar_bloqueadas(owner_engine, 2)
            await transaccion.commit()
            await asyncio.gather(reuso, login)
        finally:
            if transaccion.is_active:
                await transaccion.rollback()
            for tarea in tareas:
                if not tarea.done():
                    tarea.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)

    assert reuso.result() == 401
    assert login.result().status_code == 200, login.result().text
    posterior = login.result().cookies.get(REFRESH_COOKIE)
    assert posterior and hash_token(posterior) in await _vivas(owner_engine, email)

    assert await _refresh(client, familia) == 401
    assert await _vivas(owner_engine, email) == {hash_token(posterior)}
    assert await _refresh(client, posterior) == 200


@pytest.mark.asyncio
async def test_refresh_y_logout_concurrentes_no_revocan_otro_dispositivo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    email = "pg-refresh-logout-race@demo.com"
    familia, otro = await _dos_dispositivos(
        client, app_sessions, slug="pg-refresh-logout-race", email=email
    )
    refresh_response, logout_response = await asyncio.gather(
        client.post("/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={familia}"}),
        client.post("/auth/logout", headers={"Cookie": f"{REFRESH_COOKIE}={familia}"}),
    )
    assert refresh_response.status_code in {200, 401}, refresh_response.text
    assert logout_response.status_code == 204, logout_response.text
    vivas = await _vivas(owner_engine, email)
    assert hash_token(otro) in vivas
    if refresh_response.status_code == 200:
        nuevo = refresh_response.cookies.get(REFRESH_COOKIE)
        assert nuevo and hash_token(nuevo) in vivas
