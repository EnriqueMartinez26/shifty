"""Cada log de un request lleva el ``request_id`` del borde.

Plan de rendimiento (F0-22 dejo los logs en JSON con ``merge_contextvars``;
2026-09-24): nginx manda ``X-Edge-Request-Id`` (``$request_id``, tambien en su
access log como ``rid``), pero nadie lo ligaba al contexto de structlog, asi
que un 500 del backend no se podia cruzar con la linea del borde. Sin el
header (un request que no paso por nginx) se genera un ULID. El contexto se
limpia al terminar: un request no hereda el id del anterior.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import pytest
import structlog
from structlog.testing import capture_logs

from core.request_id import RequestIdMiddleware

logger = structlog.get_logger()


async def _pasar(
    headers: list[tuple[bytes, bytes]],
) -> tuple[list[Any], MutableMapping[str, Any]]:
    async def app(_scope: Any, _receive: Any, send: Any) -> None:
        logger.info("dentro_del_request")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    enviados: list[Any] = []

    async def send(message: Any) -> None:
        enviados.append(message)

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as eventos:
        await RequestIdMiddleware(app)(
            {"type": "http", "method": "GET", "path": "/x", "headers": headers},
            receive,
            send,
        )
    evento = next(e for e in eventos if e["event"] == "dentro_del_request")
    return enviados, evento


@pytest.mark.asyncio
async def test_liga_el_id_que_manda_el_borde() -> None:
    _, evento = await _pasar(
        [(b"x-edge-request-id", b"4f1c2a9b8e7d6c5b4a39281706f5e4d3")]
    )

    assert evento["request_id"] == "4f1c2a9b8e7d6c5b4a39281706f5e4d3"


@pytest.mark.asyncio
async def test_sin_header_genera_un_ulid() -> None:
    _, evento = await _pasar([])

    assert len(evento["request_id"]) == 26
    assert evento["request_id"].isalnum()


@pytest.mark.asyncio
async def test_un_header_hostil_no_se_loguea_tal_cual() -> None:
    _, evento = await _pasar([(b"x-edge-request-id", b'abc"\n{"event":"falso"}')])

    assert "falso" not in evento["request_id"]
    assert len(evento["request_id"]) == 26


@pytest.mark.asyncio
async def test_el_contexto_se_limpia_al_terminar() -> None:
    await _pasar([(b"x-edge-request-id", b"rid-uno")])

    assert "request_id" not in structlog.contextvars.get_contextvars()


def test_la_app_lo_registra_como_capa_mas_externa() -> None:
    """Mas afuera que todo: los logs del rate limit y del 500 tambien lo llevan."""
    from main import app

    capa: Any = app.user_middleware[0].cls
    assert capa is RequestIdMiddleware
