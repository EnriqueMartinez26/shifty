"""La identidad se resuelve UNA vez por request, con una sola lectura.

F1-01 (plan de rendimiento, R2-08/R4-01, 2026-09-24): un GET del panel pasaba
dos veces por ``get_current_user``: una desde ``block_writes_when_suspended``
(via ``get_optional_current_user``, que lo llamaba como funcion y no como
dependencia, asi que FastAPI no lo cacheaba) y otra desde la dependencia del
handler. Cada pasada eran dos ``set_config`` + ``SELECT auth_sessions`` +
``SELECT users``. Sumando el ``set_config`` inicial de ``get_db``, la
identidad costaba 9 sentencias fijas por request en Postgres.

Ahora la segunda pasada reutiliza el usuario ya resuelto en el mismo request
(y sobre la misma sesion de base), y la sesion y el usuario se leen en un solo
``SELECT ... JOIN``. La regla 1 sigue: el ``store_id`` y el
``is_global_admin`` salen de la base en CADA request, una sola vez.

Cuenta en Postgres despues del cambio: 1 (``get_db``) + 1 ``set_config`` de
bypass + 1 ``SELECT`` con JOIN + 1 ``set_config`` del contexto real = 4.
SQLite no ejecuta ``set_config`` (``_apply_tenant_context`` sale antes por
dialecto), asi que el test cuenta sus llamadas aparte.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.auth.dependencies as auth_dependencies
from core.database import _apply_tenant_context
from core.security import create_access_token, decode_token
from modules.auth.session_model import AuthSession
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

# El set_config inicial de get_db en produccion; el fixture de SQLite lo
# reemplaza por la sesion del test, que no lo ejecuta.
_SET_CONFIG_DE_GET_DB = 1


def _es_de_identidad(statement: str) -> bool:
    texto = " ".join(statement.split()).lower()
    return "auth_sessions" in texto or "from users" in texto


@pytest.mark.asyncio
async def test_un_get_del_panel_resuelve_la_identidad_una_sola_vez(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, token = await register_and_login(
        client, slug="identidad-una-vez", email="identidad-una-vez@test.com"
    )

    sentencias: list[str] = []
    aplicaciones_de_contexto = 0
    original = _apply_tenant_context

    async def contar_contexto(session: AsyncSession) -> None:
        nonlocal aplicaciones_de_contexto
        aplicaciones_de_contexto += 1
        await original(session)

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if _es_de_identidad(statement):
            sentencias.append(statement)

    monkeypatch.setattr(auth_dependencies, "_apply_tenant_context", contar_contexto)
    event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
    try:
        # /notifications lleva la guarda de suspension a nivel router Y
        # get_current_staff en el handler: las dos resoluciones de identidad.
        response = await client.get("/notifications", headers=auth_headers(token))
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)

    assert response.status_code == 200, response.text
    assert len(sentencias) == 1, (
        f"sesion + usuario en un solo SELECT, una vez por request: {sentencias}"
    )
    assert aplicaciones_de_contexto == 2, (
        "un set_config de bypass y uno del contexto real, una sola vez"
    )
    total_fijo = _SET_CONFIG_DE_GET_DB + len(sentencias) + aplicaciones_de_contexto
    assert total_fijo <= 5, f"costo fijo de identidad: {total_fijo} sentencias"


@pytest.mark.asyncio
async def test_una_sesion_revocada_sigue_siendo_401_con_el_join(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El JOIN conserva la semantica: una sesion revocada no autentica."""
    _, token = await register_and_login(
        client, slug="identidad-revocada", email="identidad-revocada@test.com"
    )
    await test_session.execute(
        update(AuthSession).values(revoked_at=datetime.now(timezone.utc))
    )
    await test_session.commit()

    response = await client.get("/notifications", headers=auth_headers(token))

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_la_sesion_de_otro_usuario_no_autentica(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """``sid`` de una sesion ajena con el ``sub`` propio: el JOIN no da fila."""
    _, token = await register_and_login(
        client, slug="identidad-ajena-a", email="identidad-ajena-a@test.com"
    )
    await register_and_login(
        client, slug="identidad-ajena-b", email="identidad-ajena-b@test.com"
    )
    payload = decode_token(token)
    ajena = await test_session.scalar(
        select(AuthSession.id).where(AuthSession.user_id != payload["sub"]).limit(1)
    )
    assert ajena is not None
    forjado = create_access_token(
        {"sub": payload["sub"], "sid": ajena, "store_id": payload.get("store_id")}
    )

    response = await client.get("/notifications", headers=auth_headers(forjado))

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_sin_token_la_guarda_opcional_no_autentica(client: AsyncClient) -> None:
    """Anonimo en un router del panel: la guarda deja pasar y el handler da 401."""
    response = await client.get("/notifications")

    assert response.status_code == 401, response.text
