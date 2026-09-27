"""Una notificacion inactiva no se marca leida por id.

B4-10 (2026-09-18): listar, contar y read-all filtraban
``Notification.is_active``, pero ``POST /notifications/{id}/read`` no: una
notificacion dada de baja no aparecia en el panel y aun asi se podia marcar
por id (respondia 200 y escribia ``read_at``). El filtro base (tienda +
activa) sale ahora de un solo lugar del repositorio.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.model import Notification, NotificationType
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


@pytest.mark.asyncio
async def test_marcar_por_id_una_inactiva_responde_404_y_no_escribe(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    publica, token = await register_and_login(
        client, slug="notif-inactiva", email="notif-inactiva@test.com"
    )
    store_id = await test_session.scalar(
        select(Store.id).where(Store.public_id == publica)
    )
    assert store_id is not None
    inactiva = Notification(
        store_id=store_id,
        type=NotificationType.PAYMENT_APPROVED.value,
        title="dada de baja",
        is_active=False,
    )
    activa = Notification(
        store_id=store_id,
        type=NotificationType.PAYMENT_APPROVED.value,
        title="vigente",
    )
    test_session.add_all([inactiva, activa])
    await test_session.commit()
    inactiva_id, activa_id = inactiva.id, activa.id

    respuesta = await client.post(
        f"/notifications/{inactiva_id}/read", headers=auth_headers(token)
    )
    assert respuesta.status_code == 404, respuesta.text
    test_session.expire_all()
    assert (
        await test_session.scalar(
            select(Notification.read_at).where(Notification.id == inactiva_id)
        )
        is None
    )

    # La activa se sigue marcando como siempre.
    ok = await client.post(
        f"/notifications/{activa_id}/read", headers=auth_headers(token)
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"updated": 1, "unread_count": 0}
