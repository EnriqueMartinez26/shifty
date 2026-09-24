"""Una respuesta que ya sale envuelta no se vuelve a serializar.

F1-02 (plan de rendimiento, R4-02/R8-07, 2026-09-24): toda respuesta 2xx se
serializaba tres veces. ``CanonicalRoute`` la envolvia en ``{success, data}``
y FastAPI la codificaba; despues ``CanonicalJsonMiddleware`` leia el cuerpo,
hacia ``json.loads``, ``jsonable_encoder`` y ``json.dumps`` de nuevo para
producir exactamente lo mismo. En ``/reports/summary`` con 5000 filas eran
0,1-0,3 s de CPU por request.

Ahora ``CanonicalRoute`` marca en el scope que su salida ya es canonica y el
middleware la deja pasar tal cual. Sigue envolviendo lo que no viene envuelto
(handlers que devuelven un ``JSONResponse`` o rutas sin ``response_model``) y
sigue desenvolviendo con ``x-raw-response`` fuera de produccion.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from httpx import AsyncClient

import core.responses as responses
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


class _Espia:
    def __init__(self) -> None:
        self.llamadas = 0
        self._original = jsonable_encoder

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.llamadas += 1
        return self._original(*args, **kwargs)


@pytest.mark.asyncio
async def test_una_ruta_canonica_no_se_recodifica_en_el_middleware(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await register_and_login(
        client, slug="sobre-sin-recodificar", email="sobre-sin-recodificar@test.com"
    )
    espia = _Espia()
    monkeypatch.setattr(responses, "jsonable_encoder", espia)

    response = await client.get(
        "/notifications",
        headers={**auth_headers(token), "x-raw-response": "false"},
    )

    assert response.status_code == 200, response.text
    cuerpo = response.json()
    assert cuerpo["success"] is True
    assert cuerpo["data"] == {"items": [], "unread_count": 0}
    assert espia.llamadas == 0, "el middleware re-serializo una respuesta canonica"
    assert int(response.headers["content-length"]) == len(response.content)


@pytest.mark.asyncio
async def test_lo_que_no_viene_envuelto_se_sigue_envolviendo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/`` es una ruta comun (sin CanonicalRoute): el middleware la envuelve."""
    espia = _Espia()
    monkeypatch.setattr(responses, "jsonable_encoder", espia)

    response = await client.get("/", headers={"x-raw-response": "false"})

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert response.json()["data"]["status"] == "online"
    assert espia.llamadas > 0


@pytest.mark.asyncio
async def test_x_raw_response_sigue_desenvolviendo_una_ruta_canonica(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="sobre-crudo", email="sobre-crudo@test.com"
    )

    response = await client.get(
        "/notifications",
        headers={**auth_headers(token), "x-raw-response": "true"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "unread_count": 0}


@pytest.mark.asyncio
async def test_la_marca_no_sale_al_cliente(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="sobre-sin-marca", email="sobre-sin-marca@test.com"
    )

    response = await client.get(
        "/notifications",
        headers={**auth_headers(token), "x-raw-response": "false"},
    )

    assert not any(nombre.startswith("x-shifty") for nombre in response.headers)
