"""B6-07 (2026-09-19): ``price`` y ``deposit_amount`` aceptaban mas de 2 decimales.

Sintoma: ``POST /services/ {"price": 10.001}`` pasaba la validacion (``float``
sin ``decimal_places``). En Postgres ``Numeric(10, 2)`` lo redondeaba en
silencio; en SQLite se guardaba tal cual y ``payments/service.py`` lo
propagaba al monto de la preferencia de Mercado Pago. Ahora es 422.

Decision: sin cambiar el tipo ni la forma serializada (el JSON sigue siendo
numero). ``Field(multiple_of=0.01)`` con ``float`` da FALSOS rechazos por
precision: medido el 2026-09-19 sobre 500.000 importes validos de 2
decimales, rechazo 5.083 (p. ej. 9624539.79). Por eso el control compara con
``Decimal(str(valor))``; ``9624539.79`` queda en la lista de aceptados.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

VALIDOS = [10.10, 0.07, 99999.99, 9624539.79, 10000000, 0, 1500]
INVALIDOS = [10.001, 0.005, 99999.999, 1.123456]


def _alta(campo: str, valor: float) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Corte",
        "duration_minutes": 30,
        "price": 10000,
    }
    if campo == "deposit_amount":
        # fixed: el monto es plata, sin el tope 100 de percent; y mode none
        # para que 0 sea valido (B6-02 exige monto > 0 si hay sena).
        payload.update(deposit_mode="none", deposit_type="fixed")
    payload[campo] = valor
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["price", "deposit_amount"])
@pytest.mark.parametrize("valor", VALIDOS)
async def test_alta_acepta_importes_con_hasta_dos_decimales(
    client: AsyncClient, campo: str, valor: float
) -> None:
    _, token = await register_and_login(
        client, slug="b6-07-ok", email="b6-07-ok@example.com"
    )
    res = await client.post(
        "/services/", headers=auth_headers(token), json=_alta(campo, valor)
    )
    assert res.status_code == 201, res.text
    assert res.json()[campo] == valor


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["price", "deposit_amount"])
@pytest.mark.parametrize("valor", INVALIDOS)
async def test_alta_rechaza_mas_de_dos_decimales(
    client: AsyncClient, campo: str, valor: float
) -> None:
    _, token = await register_and_login(
        client, slug="b6-07-mal", email="b6-07-mal@example.com"
    )
    res = await client.post(
        "/services/", headers=auth_headers(token), json=_alta(campo, valor)
    )
    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["price", "deposit_amount"])
@pytest.mark.parametrize(("valor", "esperado"), [(10.001, 422), (99999.99, 200)])
async def test_patch_aplica_la_misma_regla(
    client: AsyncClient, campo: str, valor: float, esperado: int
) -> None:
    _, token = await register_and_login(
        client, slug="b6-07-patch", email="b6-07-patch@example.com"
    )
    res = await client.post(
        "/services/", headers=auth_headers(token), json=_alta(campo, 100)
    )
    assert res.status_code == 201, res.text
    public_id = cast(str, res.json()["public_id"])

    res = await client.patch(
        f"/services/{public_id}", headers=auth_headers(token), json={campo: valor}
    )
    assert res.status_code == esperado, res.text
    guardado = await client.get(f"/services/{public_id}", headers=auth_headers(token))
    assert guardado.json()[campo] == (valor if esperado == 200 else 100)
