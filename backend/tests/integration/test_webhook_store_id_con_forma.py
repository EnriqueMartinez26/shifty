"""El ``store_id`` del webhook de Mercado Pago se valida por forma antes de la base.

2026-09-18, hallazgo B2-18: el unico parametro de query del webhook (trafico
externo sin autenticar) aceptaba cualquier texto de hasta 64 caracteres y lo
llevaba directo a dos ``WHERE`` de ``_resolve_store_for_webhook``. No habia
inyeccion (SQLAlchemy parametriza) ni 5xx, pero el endpoint mas expuesto del
modulo no usaba la forma declarada del identificador publico
(``core.validation.PUBLIC_ID_PATTERN``).

Regla 7: el rechazo por forma tiene que ser INDISTINGUIBLE del de una tienda
inexistente (mismo codigo, mismo cuerpo), para no revelar si una tienda
existe ni cambiar lo que ve Mercado Pago (sus reintentos siguen igual).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    webhook_signature_headers,
)

MALFORMADOS = ["tienda con espacios", "abc';--", "..%2f..", "ñandu", "a/b"]
INEXISTENTE = "01J0000000000000000000NADA"


async def _webhook(client: AsyncClient, store_id: str) -> tuple[int, dict[str, Any]]:
    res = await client.post(
        "/payments/webhooks/mercadopago",
        params={"store_id": store_id},
        json={"id": "evt-forma", "type": "payment", "data": {"id": "pay-forma"}},
        headers=webhook_signature_headers(
            secret="secret-demo", data_id="pay-forma", request_id="req-forma", ts="0"
        ),
    )
    return res.status_code, res.json()


@pytest.mark.asyncio
async def test_store_id_malformado_se_rechaza_sin_consultar_la_base(
    client: AsyncClient, test_engine: AsyncEngine
) -> None:
    consultas: list[str] = []

    def anotar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        if "payment_gateway_configs" in statement or "FROM stores" in statement:
            consultas.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", anotar)
    try:
        for valor in MALFORMADOS:
            codigo, _cuerpo = await _webhook(client, valor)
            assert codigo == 400, valor
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", anotar)

    assert consultas == [], "un store_id sin forma no debe llegar a la base"


@pytest.mark.asyncio
async def test_el_rechazo_por_forma_es_identico_al_de_una_tienda_inexistente(
    client: AsyncClient,
) -> None:
    """Regla 7: mismo codigo y mismo cuerpo; no revela si la tienda existe."""
    esperado = await _webhook(client, INEXISTENTE)
    assert esperado[0] == 400
    for valor in MALFORMADOS:
        assert await _webhook(client, valor) == esperado, valor
