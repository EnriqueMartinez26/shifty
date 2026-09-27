"""RequestGuardMiddleware rechaza NUL (U+0000) en body JSON, query y path.

2026-09-24 (SEG-03). Postgres no acepta NUL en un parametro de texto
(SQLSTATE 22021, CharacterNotInRepertoireError) y ``dbapi_error_handler`` lo
dejaba subir como 500. Habia 36 campos de texto sin ``reject_control_chars``
que lo dejaban pasar, varios alcanzables sin sesion (``idempotency_key`` de la
reserva publica). SQLite lo guarda sin chistar: la suite de integracion no lo
veia. El rechazo vive en un solo lugar para que ningun campo nuevo lo olvide.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from core.security_middleware import RequestGuardMiddleware, contains_json_nul


async def _eco(request: Request) -> JSONResponse:
    cuerpo = await request.body()
    return JSONResponse({"bytes": len(cuerpo), "path": request.url.path})


def _cliente() -> AsyncClient:
    app = Starlette(
        routes=[
            Route("/cosas", _eco, methods=["GET", "POST"]),
            Route("/cosas/{cosa}", _eco, methods=["GET", "PATCH"]),
        ]
    )
    return AsyncClient(
        transport=ASGITransport(app=RequestGuardMiddleware(app)),
        base_url="http://test",
    )


def _es_422_neutro(status: int, cuerpo: dict[str, object]) -> bool:
    return (
        status == 422
        and cuerpo.get("success") is False
        and cuerpo.get("error_code") == "VALIDATION_ERROR"
        and isinstance(cuerpo.get("message"), str)
        and "\x00" not in str(cuerpo)
    )


JSON = {"content-type": "application/json"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cuerpo",
    [
        b'{"nombre": "a\\u0000b"}',
        b'{"nombre": "a\\\\\\u0000b"}',
        b'{"a\\u0000": 1}',
        b'{"nombre": "a\x00b"}',
    ],
    ids=["escape", "escape-tras-barra-escapada", "en-la-clave", "byte-crudo"],
)
async def test_un_nul_en_el_body_json_es_422(cuerpo: bytes) -> None:
    async with _cliente() as cliente:
        res = await cliente.post("/cosas", content=cuerpo, headers=JSON)

    assert _es_422_neutro(res.status_code, res.json()), res.text


@pytest.mark.asyncio
async def test_un_nul_partido_entre_dos_chunks_es_422() -> None:
    async def partes() -> AsyncIterator[bytes]:
        yield b'{"nombre": "a\\u00'
        yield b'00b"}'

    async with _cliente() as cliente:
        res = await cliente.post("/cosas", content=partes(), headers=JSON)

    assert _es_422_neutro(res.status_code, res.json()), res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cuerpo",
    [
        b'{"nombre": "caf\\u00e9"}',
        b'{"nombre": "Jos\xc3\xa9"}',
        b'{"nombre": "texto \\\\u0000 literal"}',
        b'{"nombre": "\\\\\\\\u0000"}',
    ],
    ids=["escape-legitimo", "utf8", "barra-escapada", "dos-barras-escapadas"],
)
async def test_un_body_legitimo_pasa(cuerpo: bytes) -> None:
    async with _cliente() as cliente:
        res = await cliente.post("/cosas", content=cuerpo, headers=JSON)

    assert res.status_code == 200, res.text
    assert res.json()["bytes"] == len(cuerpo)


@pytest.mark.asyncio
async def test_un_nul_en_el_query_es_422() -> None:
    async with _cliente() as cliente:
        res = await cliente.get("/cosas", params={"q": "a\x00b"})

    assert _es_422_neutro(res.status_code, res.json()), res.text


@pytest.mark.asyncio
async def test_un_porcentaje_literal_en_el_query_pasa() -> None:
    async with _cliente() as cliente:
        res = await cliente.get("/cosas", params={"q": "%00 no es nul"})

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
async def test_un_nul_en_el_path_es_422(metodo: str) -> None:
    async with _cliente() as cliente:
        res = await cliente.request(metodo, "/cosas/a%00b", content=b"{}", headers=JSON)

    assert _es_422_neutro(res.status_code, res.json()), res.text


@pytest.mark.asyncio
async def test_un_porcentaje_literal_en_el_path_pasa() -> None:
    async with _cliente() as cliente:
        res = await cliente.get("/cosas/a%2500b")

    assert res.status_code == 200, res.text
    assert res.json()["path"] == "/cosas/a%00b"


def test_el_escaneo_cuenta_las_barras_que_preceden_al_escape() -> None:
    assert contains_json_nul(b"\\u0000")
    assert not contains_json_nul(b"\\\\u0000")
    assert contains_json_nul(b"\\\\\\u0000")
    assert not contains_json_nul(b"\\\\\\\\u0000")
    assert not contains_json_nul(b"u0000 \\u00e9 \\\\")
    assert contains_json_nul(b"x\x00")
