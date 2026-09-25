"""La tienda acepta los terminos B2B y queda la constancia (L1, O-6 y 4.1).

2026-09-25. El alta de la tienda y de su admin la hace el superadmin y nadie
aceptaba nada. ``POST /stores/me/terms-acceptance`` registra que el admin de
la tienda acepto la version vigente (``STORE_TERMS_VERSION``): tienda,
usuario, version, fecha y un hash de la IP (HMAC con clave derivada de
``SECRET_KEY``; la IP en claro no se guarda). ``GET`` devuelve la ultima
aceptacion y si cubre la version vigente. No bloquea el panel: que hacer si
falta la aceptacion lo decide el front. Aceptar sigue permitido con la
tienda suspendida (``SUSPENSION_ALLOWED_WRITES``).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.billing.dependencies import SUSPENSION_ALLOWED_WRITES
from modules.legal.model import StoreTermsAcceptance
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_fiado_del_profesional import _login, _usuario

RUTA = "/stores/me/terms-acceptance"


@pytest.mark.asyncio
async def test_el_admin_acepta_la_version_vigente_y_queda_la_constancia(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token = await register_and_login(
        client, slug="b2b-acepta", email="b2b-acepta@example.com"
    )
    headers = {**auth_headers(token), "X-Forwarded-For": "203.0.113.7"}

    antes = await client.get(RUTA, headers=headers)
    assert antes.status_code == 200, antes.text
    assert antes.json() == {
        "current_version": "2026-09-25",
        "current_version_accepted": False,
        "latest": None,
    }

    alta = await client.post(RUTA, headers=headers)
    assert alta.status_code == 201, alta.text
    assert alta.json()["terms_version"] == "2026-09-25"
    assert set(alta.json()) == {"terms_version", "accepted_at", "accepted_by"}

    despues = await client.get(RUTA, headers=headers)
    assert despues.json()["current_version_accepted"] is True
    assert despues.json()["latest"]["terms_version"] == "2026-09-25"

    fila = (await test_session.execute(select(StoreTermsAcceptance))).scalar_one()
    assert fila.terms_version == "2026-09-25"
    assert fila.ip_hash and "203.0.113.7" not in fila.ip_hash
    assert len(fila.ip_hash) == 64


@pytest.mark.asyncio
async def test_una_version_nueva_deja_la_aceptacion_vieja_sin_cubrir(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token = await register_and_login(
        client, slug="b2b-nueva", email="b2b-nueva@example.com"
    )
    assert (await client.post(RUTA, headers=auth_headers(token))).status_code == 201

    monkeypatch.setattr(settings, "STORE_TERMS_VERSION", "2027-01-01")
    estado = await client.get(RUTA, headers=auth_headers(token))

    assert estado.json()["current_version"] == "2027-01-01"
    assert estado.json()["current_version_accepted"] is False
    assert estado.json()["latest"]["terms_version"] == "2026-09-25"


@pytest.mark.asyncio
async def test_solo_el_admin_de_la_tienda_acepta(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="b2b-roles", email="b2b-roles@example.com"
    )
    await _usuario(
        client,
        token,
        email="pro-b2b-roles@example.com",
        rol="staff",
        nombre="Pro",
        apellido="Fesional",
    )
    profesional = await _login(client, "pro-b2b-roles@example.com")

    assert (await client.post(RUTA, headers=profesional)).status_code == 403
    assert (await client.get(RUTA, headers=profesional)).status_code == 403


def test_aceptar_sigue_permitido_con_la_tienda_suspendida() -> None:
    assert ("POST", RUTA) in SUSPENSION_ALLOWED_WRITES
