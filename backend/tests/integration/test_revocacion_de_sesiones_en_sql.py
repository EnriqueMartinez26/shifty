"""Las revocaciones de sesion se hacen con un UPDATE, no fila por fila.

Auditoria B3-10, 2026-09-17. Sintoma: las cuatro revocaciones
(``revoke_sessions_for_user``, ``revoke_store_sessions``,
``revoke_user_sessions``, ``revoke_all_sessions``) hacian el mismo
``SELECT`` de todas las sesiones vivas, asignaban ``revoked_at`` en un ``for``
de Python y contaban a mano. ``revoke_all_sessions`` -- el boton de panico del
superadmin -- lo hacia SIN filtro: hidrataba todas las ``auth_sessions`` vivas
de todas las tiendas y emitia un UPDATE por fila. Con 50k sesiones agota el
time limit y, si falla a la mitad, no revoca nada (regla 11 y criterio 5).

El mismo modulo ya usaba ``update(AuthSession).values(revoked_at=now)`` con
``rowcount`` en la rotacion del refresh: es ese patron el que se unifica.

Regla 15 de CLAUDE.md: la revocacion sigue siendo la misma y
``preserve_refresh_token`` sigue salvando la sesion desde la que el usuario
hace el cambio; eso es lo que fijan los tests de comportamiento.
"""

import ast
import inspect

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auth import service as auth_service
from modules.auth.session_model import AuthSession
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

REVOCACIONES = (
    "revoke_sessions_for_user",
    "revoke_store_sessions",
    "revoke_user_sessions",
    "revoke_all_sessions",
)


@pytest.mark.parametrize("nombre", REVOCACIONES)
def test_ninguna_revocacion_itera_las_filas_en_python(nombre: str) -> None:
    fn = getattr(auth_service, nombre)
    arbol = ast.parse(inspect.getsource(fn).lstrip())
    bucles = [nodo for nodo in ast.walk(arbol) if isinstance(nodo, ast.For)]
    assert not bucles, (
        f"{nombre} vuelve a recorrer las sesiones en un for: la revocacion es "
        "un UPDATE con rowcount (regla 11)."
    )


async def _sesiones_vivas(db: AsyncSession) -> int:
    total = await db.execute(
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.revoked_at.is_(None))
    )
    return int(total.scalar_one())


@pytest.mark.asyncio
async def test_revocar_la_tienda_no_toca_las_sesiones_de_otra(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token_a = await register_and_login(
        client, slug="revoca-a", email="revoca-a@test.com"
    )
    _, token_b = await register_and_login(
        client, slug="revoca-b", email="revoca-b@test.com"
    )

    res = await client.post(
        "/auth/sessions/revoke-store", headers=auth_headers(token_b)
    )
    assert res.status_code == 200, res.text
    assert res.json()["revoked_sessions"] >= 1

    # La tienda A sigue de pie: el UPDATE no puede cruzar el limite de tienda.
    viva = await client.get("/me", headers=auth_headers(token_a))
    assert viva.status_code == 200, "la revocacion de otra tienda mato esta sesion"
    muerta = await client.get("/me", headers=auth_headers(token_b))
    assert muerta.status_code in {401, 403}


@pytest.mark.asyncio
async def test_el_boton_de_panico_del_superadmin_revoca_todas_las_tiendas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    from modules.users.model import User

    _, token_a = await register_and_login(
        client, slug="panico-a", email="panico-a@test.com"
    )
    _, token_b = await register_and_login(
        client, slug="panico-b", email="panico-b@test.com"
    )
    usuario = (
        await test_session.execute(
            select(User).where(User.email == "panico-a@test.com")
        )
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()

    login = await client.post(
        "/auth/login",
        json={"email": "panico-a@test.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    token_global = str(login.json()["access_token"])

    res = await client.post(
        "/auth/sessions/revoke-all", headers=auth_headers(token_global)
    )
    assert res.status_code == 200, res.text
    assert res.json()["revoked_sessions"] >= 3

    assert await _sesiones_vivas(test_session) == 0, (
        "quedaron sesiones vivas despues del boton de panico"
    )
    for etiqueta, tok in (("A", token_a), ("B", token_b), ("global", token_global)):
        muerta = await client.get("/me", headers=auth_headers(tok))
        assert muerta.status_code in {401, 403}, f"la sesion {etiqueta} sobrevivio"


@pytest.mark.asyncio
async def test_cambiar_password_conserva_la_sesion_que_lo_pidio(
    client: AsyncClient,
) -> None:
    """regla 15: el cambio revoca la familia MENOS la sesion actual.

    Es el unico caso de ``preserve_refresh_token``; con el UPDATE masivo se
    expresa como ``refresh_token_hash != hash(actual)``.
    """
    _, token_a = await register_and_login(
        client, slug="preserva", email="preserva@test.com"
    )
    otro = await client.post(
        "/auth/login",
        json={"email": "preserva@test.com", "password": "Password123!"},
    )
    assert otro.status_code == 200, otro.text
    token_b = str(otro.json()["access_token"])

    # El cookie jar quedo con el refresh de la SEGUNDA sesion: esa es "la
    # actual" para el cambio de contrasena.
    res = await client.put(
        "/auth/change-password",
        headers=auth_headers(token_b),
        json={
            "current_password": "Password123!",
            "new_password": "OtraClaveSegura456",
        },
    )
    assert res.status_code == 200, res.text

    # La sesion vieja cae...
    muerta = await client.get("/me", headers=auth_headers(token_a))
    assert muerta.status_code in {401, 403}
    # ...y la que pidio el cambio sigue pudiendo refrescar.
    sigue = await client.post("/auth/refresh")
    assert sigue.status_code == 200, (
        "la sesion que pidio el cambio se revoco: preserve_refresh_token se perdio"
    )
