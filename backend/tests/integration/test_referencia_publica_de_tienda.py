"""FF-16: "Mis turnos" con la tienda suspendida.

2026-09-24. Sintoma (revision-funcional-front.md, FF-16): con la tienda
suspendida el cliente no podia entrar a "Mis turnos" para cancelar o
reprogramar ("Negocio no encontrado"), aunque el backend se lo permite
(B1-06): el front resuelve slug -> tienda con ``GET /public/stores/{slug}``,
que desaparece (404) mientras la suscripcion este suspendida.

Contrato (aditivo): ``GET /public/stores/{slug}/ref`` devuelve SOLO
``{store_public_id, name, accepts_new_bookings}`` para una tienda activa,
suspendida o no; 404 neutro (el de la vitrina) si no existe o esta dada de
baja. De la suscripcion no expone mas que el booleano. ``no-store`` y rate
limit ``public-read``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.rate_limit import _policy_for_request
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_suspension_por_endpoint import _suspender


@pytest.mark.asyncio
async def test_tienda_activa_devuelve_solo_la_referencia(client: AsyncClient) -> None:
    store, _token = await register_and_login(
        client, slug="ref-activa", email="ref-activa@t.com"
    )

    res = await client.get("/public/stores/Ref-Activa/ref")

    assert res.status_code == 200, res.text
    assert res.json() == {
        "store_public_id": store,
        "name": "Tienda ref-activa",
        "accepts_new_bookings": True,
    }
    assert res.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_tienda_suspendida_sigue_resolviendo_sin_tomar_reservas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, _token = await register_and_login(
        client, slug="ref-suspendida", email="ref-suspendida@t.com"
    )
    await _suspender(test_session, store)

    vitrina = await client.get("/public/stores/ref-suspendida")
    ref = await client.get("/public/stores/ref-suspendida/ref")

    assert vitrina.status_code == 404
    assert ref.status_code == 200, ref.text
    assert ref.json() == {
        "store_public_id": store,
        "name": "Tienda ref-suspendida",
        "accepts_new_bookings": False,
    }


@pytest.mark.asyncio
async def test_inexistente_o_dada_de_baja_404_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, _token = await register_and_login(
        client, slug="ref-baja", email="ref-baja@t.com"
    )
    await test_session.execute(
        update(Store).where(Store.public_id == store).values(is_active=False)
    )
    await test_session.commit()

    baja = await client.get("/public/stores/ref-baja/ref")
    inexistente = await client.get("/public/stores/no-existe/ref")
    vitrina = await client.get("/public/stores/no-existe")

    assert baja.status_code == inexistente.status_code == 404
    assert baja.json()["error_code"] == "STORE_NOT_FOUND"
    # Mismo sobre que la vitrina: sin pistas de por que no esta.
    assert inexistente.json().keys() == vitrina.json().keys()
    assert inexistente.json()["error_code"] == vitrina.json()["error_code"]


def test_el_rate_limit_es_el_de_lectura_publica() -> None:
    politica, _limite = _policy_for_request("GET", "/public/stores/tienda/ref")
    assert politica == "public-read"
