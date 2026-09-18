"""Dar de baja una promocion libera su codigo para una promocion nueva.

2026-09-17, hallazgo B2-14: el borrado es logico (``is_active=False``) pero el
pre-chequeo de duplicados y la restriccion ``uq_store_promotions_store_code``
no distinguian activas de dadas de baja. Reproduccion:
``POST /promotions {code: VERANO20}`` -> ``DELETE`` -> ``POST`` otra vez ->
409 ``PROMOTION_CODE_DUPLICATE`` para siempre, sin ninguna promocion activa
que lo explique. La unicidad pasa a un indice unico parcial sobre las
activas (mismo patron que ``uq_users_client_phone_per_store``); los canjes
conservan ``code_snapshot`` y ``promotion_id``, asi que la trazabilidad no
depende del codigo vivo.
"""

from __future__ import annotations

from typing import cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)


async def _crear(client: AsyncClient, token: str, code: str, value: int = 10) -> str:
    res = await client.post(
        "/promotions/",
        headers=auth_headers(token),
        json={
            "code": code,
            "title": "Verano",
            "promotion_type": "percent",
            "value": value,
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


@pytest.mark.asyncio
async def test_el_codigo_de_una_promocion_borrada_se_puede_reusar(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="promo-reuso", email="promo-reuso@test.com"
    )
    servicio = await create_service(client, token)  # precio 10000
    vieja = await _crear(client, token, "VERANO20", value=10)
    borrar = await client.delete(f"/promotions/{vieja}", headers=auth_headers(token))
    assert borrar.status_code == 204, borrar.text

    nueva = await _crear(client, token, "VERANO20", value=20)
    assert nueva != vieja

    # El canje resuelve la ACTIVA (20%), no la dada de baja, y sin 500 por
    # tener dos filas con el mismo codigo.
    preview = await client.get(
        f"/promotions/preview?service_id={servicio}&code=VERANO20",
        headers=auth_headers(token),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["discount_amount"] == "2000.00"


@pytest.mark.asyncio
async def test_dos_promociones_activas_siguen_sin_poder_compartir_codigo(
    client: AsyncClient,
) -> None:
    """Guarda viva: la unicidad por tienda se conserva entre las activas."""
    _store, token = await register_and_login(
        client, slug="promo-dup", email="promo-dup@test.com"
    )
    await _crear(client, token, "OTONIO")
    duplicada = await client.post(
        "/promotions/",
        headers=auth_headers(token),
        json={"code": "OTONIO", "title": "Otra", "value": 5},
    )
    assert duplicada.status_code == 409, duplicada.text
    assert duplicada.json()["error_code"] == "PROMOTION_CODE_DUPLICATE"


@pytest.mark.asyncio
async def test_reactivar_una_promocion_no_pisa_a_la_activa_con_su_codigo(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="promo-react", email="promo-react@test.com"
    )
    vieja = await _crear(client, token, "INVIERNO")
    await client.delete(f"/promotions/{vieja}", headers=auth_headers(token))
    await _crear(client, token, "INVIERNO")

    reactivar = await client.patch(
        f"/promotions/{vieja}",
        headers=auth_headers(token),
        json={"is_active": True},
    )
    assert reactivar.status_code == 409, reactivar.text
    assert reactivar.json()["error_code"] == "PROMOTION_CODE_DUPLICATE"


@pytest.mark.asyncio
async def test_si_solo_queda_la_borrada_el_canje_dice_que_no_esta_activa(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="promo-sola", email="promo-sola@test.com"
    )
    servicio = await create_service(client, token)
    primera = await _crear(client, token, "PRIMAVERA")
    await client.delete(f"/promotions/{primera}", headers=auth_headers(token))
    segunda = await _crear(client, token, "PRIMAVERA")
    await client.delete(f"/promotions/{segunda}", headers=auth_headers(token))

    preview = await client.get(
        f"/promotions/preview?service_id={servicio}&code=PRIMAVERA",
        headers=auth_headers(token),
    )
    assert preview.status_code == 422, preview.text
    assert "no esta activa" in preview.json()["message"]
