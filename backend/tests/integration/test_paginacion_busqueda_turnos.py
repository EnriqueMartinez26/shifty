"""``page`` sin tope superior en la busqueda de turnos (regla 9 de CLAUDE.md).

Audit B1-03 (2026-09-17). Sintoma: ``GET /appointments/search?page=<enorme>``
llegaba crudo al ``OFFSET (page - 1) * page_size`` y desbordaba el entero de
la base: 500. ``page_size`` ya llevaba ``ge`` y ``le``; ``page`` solo ``ge``.
Es el mismo incidente documentado el 2026-09-04 para ``offset``, sin cerrar
en este endpoint. Debe ser 422, nunca 500.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


@pytest.mark.asyncio
async def test_page_desbordado_en_la_busqueda_de_turnos_responde_422(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="pag-turnos", email="pag-turnos@example.com"
    )
    desborde = await client.get(
        "/appointments/search?page=99999999999999999999",
        headers=auth_headers(token),
    )
    assert desborde.status_code == 422, desborde.text

    # Justo por encima del tope: tambien 422, no 500.
    demasiado = await client.get(
        "/appointments/search?page=10001", headers=auth_headers(token)
    )
    assert demasiado.status_code == 422, demasiado.text

    # Los valores validos siguen funcionando (incluido el tope).
    tope = await client.get(
        "/appointments/search?page=10000", headers=auth_headers(token)
    )
    assert tope.status_code == 200, tope.text
    assert tope.json()["page"] == 10000
    ok = await client.get(
        "/appointments/search?page=1&page_size=20", headers=auth_headers(token)
    )
    assert ok.status_code == 200, ok.text
