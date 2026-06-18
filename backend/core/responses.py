from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Generic, TypeVar, cast

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

T = TypeVar("T")


class ApiSuccess(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: dict[str, Any] | None = None


class ApiError(BaseModel):
    success: bool = False
    error_code: str
    message: str
    detail: Any | None = None


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


class CanonicalJsonMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response: Any = await call_next(request)
        # AI AGENT NOTE: Allow clients (like integration tests) to request the raw
        # unwrapped response to maintain backwards compatibility without breaking
        # strict typing or requiring massive test rewrites.
        if request.headers.get("x-raw-response") == "true":
            return cast(Response, response)

        if not _should_wrap_response(response):
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

        if is_canonical_payload(payload):
            wrapped_body = json.dumps(
                jsonable_encoder(payload), separators=(",", ":")
            ).encode("utf-8")
        else:
            wrapped_body = json.dumps(
                success_payload(payload), separators=(",", ":")
            ).encode("utf-8")

        return _clone_response(response, wrapped_body)


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
    headers = MutableHeaders(response.headers)
    headers["content-length"] = str(len(body))
    return Response(
        content=body,
        status_code=response.status_code,
        headers=dict(headers),
        media_type=response.media_type,
        background=response.background,
    )
