"""read-all marca en una sola sentencia, sin traer las filas a memoria.

B4-06 (2026-09-18): ``POST /notifications/read-all`` cargaba todas las no
leidas de la tienda como objetos ORM y las marcaba una por una (un UPDATE por
fila en el flush). Una tienda que nunca abrio la campanita acumula miles de
filas y un read-all las materializaba todas (regla 11: se agrega en SQL, no
en memoria). Ahora es un ``UPDATE ... WHERE store_id AND read_at IS NULL AND
is_active`` y ``updated`` sale del ``rowcount``.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.notifications.model import Notification, NotificationType
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _store_id(session: AsyncSession, store_public_id: str) -> str:
    store_id = await session.scalar(
        select(Store.id).where(Store.public_id == store_public_id)
    )
    assert store_id is not None
    return str(store_id)


@pytest.mark.asyncio
async def test_read_all_es_un_solo_update_sin_cargar_filas(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    publica, token = await register_and_login(
        client, slug="notif-read-all-sql", email="notif-read-all-sql@test.com"
    )
    publica_ajena, _ = await register_and_login(
        client, slug="notif-read-all-ajena", email="notif-read-all-ajena@test.com"
    )
    store_id = await _store_id(test_session, publica)
    ajena_id = await _store_id(test_session, publica_ajena)

    for i in range(5):
        test_session.add(
            Notification(
                store_id=store_id,
                type=NotificationType.PAYMENT_APPROVED.value,
                title=f"pendiente {i}",
            )
        )
    inactiva = Notification(
        store_id=store_id,
        type=NotificationType.PAYMENT_APPROVED.value,
        title="inactiva",
        is_active=False,
    )
    ya_leida = Notification(
        store_id=store_id,
        type=NotificationType.PAYMENT_APPROVED.value,
        title="ya leida",
    )
    ya_leida.mark_read()
    ajena = Notification(
        store_id=ajena_id,
        type=NotificationType.PAYMENT_APPROVED.value,
        title="de otra tienda",
    )
    test_session.add_all([inactiva, ya_leida, ajena])
    await test_session.commit()
    ya_leida_id = ya_leida.id
    test_session.expire_all()
    leida_antes = await test_session.scalar(
        select(Notification.read_at).where(Notification.id == ya_leida_id)
    )
    assert leida_antes is not None

    sentencias: list[tuple[str, bool]] = []

    def _registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        executemany: bool,
    ) -> None:
        if "notifications" in statement.lower():
            sentencias.append((" ".join(statement.split()).lower(), executemany))

    event.listen(test_engine.sync_engine, "before_cursor_execute", _registrar)
    try:
        response = await client.post(
            "/notifications/read-all", headers=auth_headers(token)
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _registrar)

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 5, "unread_count": 0}

    updates = [s for s in sentencias if s[0].startswith("update notifications")]
    assert len(updates) == 1, f"se esperaba un solo UPDATE: {updates}"
    assert updates[0][1] is False, "el UPDATE no puede ser un executemany por fila"
    cargas = [
        s
        for s in sentencias
        if s[0].startswith("select") and "notifications.title" in s[0]
    ]
    assert cargas == [], f"read-all no debe materializar filas: {cargas}"

    test_session.expire_all()
    estado = {
        n.title: n.read_at
        for n in (await test_session.execute(select(Notification))).scalars()
    }
    assert all(estado[f"pendiente {i}"] is not None for i in range(5))
    assert estado["inactiva"] is None, "una inactiva no se marca"
    assert estado["de otra tienda"] is None, "read-all no cruza tiendas"
    assert estado["ya leida"] == leida_antes, "no se pisa el read_at previo"
