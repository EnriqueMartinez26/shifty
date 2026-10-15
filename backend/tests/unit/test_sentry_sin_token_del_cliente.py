"""Sentry no recibe el token del cliente (``X-Client-Token``).

Revision del PR #183 (2026-10-14): ``_scrub_event`` sacaba solo
``authorization``, ``cookie`` y ``x-signature`` de los headers, y ni los
``SENSITIVE_HEADERS`` del SDK ni su ``EventScrubber`` cubren
``x-client-token``. El token es un bearer de 30 minutos cuyo payload lleva el
telefono en claro: salia en los eventos de error y en las transacciones
muestreadas, y la integracion ASGI puede ademas dejarlo en los atributos de
los spans (``http.request.header.x-client-token``).
"""

from __future__ import annotations

import json
from typing import Any

import core.observability as observability

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJwaG9uZSI6Iis1NDkxMTU1NTUwMDQyIn0.firma"
BEARER = "Bearer panel.access.token"


def _headers() -> dict[str, str]:
    return {
        "user-agent": "x",
        "x-client-token": TOKEN,
        "X-Client-Token": TOKEN,
        "X-CLIENT-TOKEN": TOKEN,
        "AUTHORIZATION": BEARER,
    }


def _limpio(evento: dict[str, Any]) -> str:
    resultado = observability._scrub_event(evento, {})  # type: ignore[arg-type]
    assert resultado is not None
    return json.dumps(resultado)


def test_un_evento_de_error_sale_sin_el_token_del_cliente() -> None:
    crudo = _limpio(
        {
            "transaction": "/public/client/appointments/{public_id}/cancel",
            "request": {"url": "https://x/api/public/x", "headers": _headers()},
        }
    )

    assert TOKEN not in crudo
    assert BEARER not in crudo
    assert "user-agent" in crudo


def test_una_transaccion_sale_sin_el_token_ni_en_los_spans() -> None:
    atributos = {
        "http.request.header.x-client-token": TOKEN,
        "http.request.header.authorization": BEARER,
        "http.request.method": "PATCH",
    }
    crudo = _limpio(
        {
            "type": "transaction",
            "transaction": "/public/client/appointments/{public_id}/reschedule",
            "request": {"url": "https://x/api/public/x", "headers": _headers()},
            "contexts": {"trace": {"data": dict(atributos)}},
            "spans": [
                {"op": "http.server", "data": dict(atributos)},
                {"op": "db", "data": {"db.system": "postgresql"}},
                {"op": "sin-data"},
            ],
        }
    )

    assert TOKEN not in crudo
    assert BEARER not in crudo
    assert "http.request.method" in crudo
