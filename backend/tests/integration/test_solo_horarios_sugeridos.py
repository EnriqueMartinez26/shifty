"""Funcion ``suggested_slots_only``: el portal no ofrece "Ver todos".

2026-11-17 (decision de Mateo, pedido de una tienda en produccion): una
clienta tocaba "Ver todos" en la reserva publica y tomaba un horario que deja
un hueco donde ya no entra otro turno del servicio (las 18 en una agenda de
servicios de 2 h que la tienda vende a las 15, 17 y 19). Con la funcion
prendida, la disponibilidad publica ignora ``force_all`` y devuelve solo la
grilla filtrada; apagada (el default), nada cambia.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.test_caracterizacion_disponibilidad import (
    GRILLA_COMPLETA_PUBLICA,
    _agenda,
    _congelar,
    _resumen,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)

FLAG = "suggested_slots_only"


async def _prender(client: AsyncClient, token: str) -> None:
    res = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={FLAG: True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["flags"][FLAG] is True


@pytest.mark.asyncio
async def test_prendida_el_portal_ignora_force_all(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, token, service, _staff, dia = await _agenda(client, monkeypatch)
    _congelar(monkeypatch, dia)
    await _prender(client, token)
    params = {
        "store_public_id": store,
        "service_id": service,
        "date": dia.isoformat(),
    }

    filtrada = await client.get("/public/availability", params=params)
    forzada = await client.get(
        "/public/availability", params={**params, "force_all": "true"}
    )

    assert filtrada.status_code == 200, filtrada.text
    assert forzada.status_code == 200, forzada.text
    assert _resumen(forzada.json()) == _resumen(filtrada.json())
    assert _resumen(forzada.json()) != GRILLA_COMPLETA_PUBLICA


@pytest.mark.asyncio
async def test_apagada_force_all_sigue_mostrando_la_grilla_completa(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _token, service, _staff, dia = await _agenda(client, monkeypatch)
    _congelar(monkeypatch, dia)

    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
            "force_all": "true",
        },
    )

    assert res.status_code == 200, res.text
    assert _resumen(res.json()) == GRILLA_COMPLETA_PUBLICA


@pytest.mark.asyncio
async def test_la_vitrina_publica_expone_la_funcion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token, _service, _staff, _dia = await _agenda(client, monkeypatch)

    antes = await client.get("/public/stores/carac-dispo")
    assert antes.status_code == 200, antes.text
    assert antes.json()["feature_flags"][FLAG] is False

    await _prender(client, token)

    despues = await client.get("/public/stores/carac-dispo")
    assert despues.status_code == 200, despues.text
    assert despues.json()["feature_flags"][FLAG] is True
