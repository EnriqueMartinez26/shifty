"""``GET /promotions/preview`` exige el mismo rol que el resto de ``/promotions``.

2026-09-20, hallazgo AUD2-B2-15: todos los handlers de promociones llamaban a
``_require_admin`` salvo ``preview_promotion``. Cualquier usuario autenticado
de la tienda (``staff``) podia cotizar cualquier codigo y, por el mensaje de
error, distinguir "no existe" de "existe pero vencio / llego al tope", sin
rate limit propio. No habia comentario que justificara la excepcion, y
``docs/ROLE_MATRIX.md`` declara deriva (CLAUDE.md §5): la unica fuente es el
codigo, y una excepcion sin motivo escrito se replica.

Sintoma: con token de personal (``role = staff``) el preview respondia 200
con la cotizacion (o 422 con el motivo del rechazo); ahora 403, igual que
listar, crear, editar o dar de baja.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)

EMAIL = "promo-preview-staff@test.com"


async def _como_personal(test_session: AsyncSession, email: str) -> None:
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.role = UserRole.STAFF
    usuario.is_global_admin = False
    await test_session.commit()


async def _preview(client: AsyncClient, token: str, servicio: str, code: str) -> int:
    res = await client.get(
        f"/promotions/preview?service_id={servicio}&code={code}",
        headers=auth_headers(token),
    )
    return res.status_code


@pytest.mark.asyncio
async def test_el_personal_no_cotiza_promociones(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token = await register_and_login(
        client, slug="promo-preview-staff", email=EMAIL
    )
    servicio = await create_service(client, token)
    alta = await client.post(
        "/promotions/",
        headers=auth_headers(token),
        json={"code": "MOSTRADOR10", "title": "Mostrador", "value": 10},
    )
    assert alta.status_code == 201, alta.text

    # El administrador sigue cotizando.
    assert await _preview(client, token, servicio, "MOSTRADOR10") == 200

    # El contexto de rol se relee de la base por request (regla 1): el mismo
    # token pasa a actuar como personal sin volver a loguearse.
    await _como_personal(test_session, EMAIL)

    assert await _preview(client, token, servicio, "MOSTRADOR10") == 403
    # Tampoco puede sondear codigos: un codigo inexistente responde lo mismo
    # que uno valido, no 422 con el motivo.
    assert await _preview(client, token, servicio, "NOEXISTE") == 403

    # Guarda viva: los vecinos del preview siguen cerrados al personal.
    listado = await client.get("/promotions/", headers=auth_headers(token))
    assert listado.status_code == 403, listado.text
