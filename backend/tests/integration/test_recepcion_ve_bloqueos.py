"""FF-14: la recepcion ve los bloqueos en su agenda (solo lectura).

2026-09-24. Sintoma (revision-funcional-front.md, FF-14): la agenda de la
recepcion no mostraba los bloqueos porque ``GET /appointment-blocks/`` le
respondia 403, y podia ofrecer un horario bloqueado. Decision: la recepcion
lee los bloqueos de la tienda; crear, editar y borrar siguen siendo del
admin y del profesional. El profesional no se acota a su agenda: la agenda
del dia (``GET /appointments/``) tampoco lo acota, y ya leia todos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

PASSWORD = "Password123!"


@pytest.mark.asyncio
async def test_la_recepcion_lee_los_bloqueos_y_no_los_escribe(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, token = await register_and_login(
        client, slug="recep-bloq", email="recep-bloq@t.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-recep-bloq@t.com")
    inicio = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=13, minute=0, second=0, microsecond=0
    )
    rango = {
        "staff_id": staff,
        "starts_at": inicio.isoformat(),
        "ends_at": (inicio + timedelta(hours=1)).isoformat(),
        "reason": "Tramite",
    }
    creado = await client.post(
        "/appointment-blocks/", headers=auth_headers(token), json=rango
    )
    assert creado.status_code == 201, creado.text
    store_id = (
        await test_session.execute(select(Store.id).where(Store.public_id == store))
    ).scalar_one()
    test_session.add(
        User(
            email="recepcion-bloq@t.com",
            hashed_password=hash_password(PASSWORD),
            first_name="Recep",
            last_name="Cion",
            role=UserRole.RECEPTIONIST,
            store_id=store_id,
        )
    )
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": "recepcion-bloq@t.com", "password": PASSWORD}
    )
    recepcion = auth_headers(str(login.json()["access_token"]))

    lista = await client.get("/appointment-blocks/", headers=recepcion)
    alta = await client.post("/appointment-blocks/", headers=recepcion, json=rango)
    baja = await client.delete(
        f"/appointment-blocks/{creado.json()['public_id']}", headers=recepcion
    )

    assert lista.status_code == 200, lista.text
    assert [b["public_id"] for b in lista.json()] == [creado.json()["public_id"]]
    assert alta.status_code == 403, alta.text
    assert baja.status_code == 403, baja.text
