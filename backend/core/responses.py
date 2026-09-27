from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any, Generic, TypeVar, cast

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.config import Environment, settings

T = TypeVar("T")


class ApiSuccess(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: dict[str, Any] | None = None


def success_payload(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True, "data": jsonable_encoder(data)}
    if meta is not None:
        payload["meta"] = jsonable_encoder(meta)
    return payload


def error_payload(
    error_code: str, message: str, detail: Any | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": message,
    }
    if detail is not None:
        payload["detail"] = jsonable_encoder(detail)
    return payload


def success_response(
    data: Any, status_code: int = 200, meta: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=success_payload(data, meta))


def error_response(
    error_code: str,
    message: str,
    status_code: int,
    detail: Any | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(error_code, message, detail),
        headers=headers,
    )


def is_canonical_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if "success" not in payload or not isinstance(payload["success"], bool):
        return False
    if payload["success"]:
        return "data" in payload
    return "error_code" in payload and "message" in payload


# Clave del scope ASGI con la que ``CanonicalRoute`` avisa que el cuerpo ya
# salio envuelto y validado contra ``ApiSuccess`` (F1-02). Vive en el scope y
# no en un header: no puede llegar al cliente ni la puede mandar el cliente.
_CANONICAL_BODY_SCOPE_KEY = "shifty.canonical_body"


def mark_canonical_body(scope: MutableMapping[str, Any]) -> None:
    scope[_CANONICAL_BODY_SCOPE_KEY] = True


def raw_response_requested(request: Request) -> bool:
    """Unico lugar que decide si la respuesta sale sin el sobre canonico.

    `x-raw-response: true` es un interruptor para los tests de integracion
    (piden el recurso pelado en vez de `{success, data}`). En produccion se
    ignora: el contrato con los clientes no puede depender de un header que
    manda cualquiera (B7-08, 2026-09-19). Los errores nunca se desenvuelven.
    """
    if settings.ENV == Environment.PRODUCTION:
        return False
    return request.headers.get("x-raw-response") == "true"


class CanonicalJsonMiddleware(BaseHTTPMiddleware):
    """Una sola capa decide el sobre de las respuestas exitosas.

    Envuelve en `{success, data}` lo que no venga envuelto y, si
    `raw_response_requested`, desenvuelve lo que `CanonicalRoute` ya envolvio.
    Antes el handler de `CanonicalRoute` tomaba la misma decision por su
    cuenta, con otras reglas.

    Lo que `CanonicalRoute` ya envolvio sale tal cual (F1-02, plan de
    rendimiento): leerlo, decodificarlo y volver a codificarlo producia los
    mismos bytes y costaba 7-13 % del request, mas en payloads grandes.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response: Any = await call_next(request)
        if not _should_wrap_response(response):
            return cast(Response, response)

        raw = raw_response_requested(request)
        if not raw and request.scope.get(_CANONICAL_BODY_SCOPE_KEY):
            return cast(Response, response)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if not body:
            return _clone_response(response, body)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return _clone_response(response, body)

        if raw:
            if is_canonical_payload(payload) and payload["success"] is True:
                return _clone_response(response, _render_json(payload["data"]))
            return _clone_response(response, body)

        if is_canonical_payload(payload):
            wrapped_body = json.dumps(
                jsonable_encoder(payload), separators=(",", ":")
            ).encode("utf-8")
        else:
            wrapped_body = json.dumps(
                success_payload(payload), separators=(",", ":")
            ).encode("utf-8")

        return _clone_response(response, wrapped_body)


def _render_json(content: Any) -> bytes:
    """Mismo render que `JSONResponse`."""
    return json.dumps(
        jsonable_encoder(content),
        ensure_ascii=False,
        allow_nan=False,
        indent=None,
        separators=(",", ":"),
    ).encode("utf-8")


def _should_wrap_response(response: Response) -> bool:
    if (
        response.status_code == 204
        or response.status_code < 200
        or response.status_code >= 300
    ):
        return False
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return False
    return response.headers.get("content-disposition") is None


def _clone_response(response: Response, body: bytes) -> Response:
    clone = Response(
        content=body,
        status_code=response.status_code,
        media_type=response.media_type,
        background=response.background,
    )
    # Se preservan los raw_headers ORIGINALES: `dict(headers)` colapsa las
    # claves repetidas y una respuesta con dos Set-Cookie (p. ej. login con
    # access + refresh) perdia una de las cookies en silencio. Solo se ajusta
    # content-length al nuevo body.
    raw = [
        (key, value) for key, value in response.raw_headers if key != b"content-length"
    ]
    raw.append((b"content-length", str(len(body)).encode("latin-1")))
    clone.raw_headers = raw
    return clone
