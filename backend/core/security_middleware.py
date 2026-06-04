import json
from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import Environment, settings


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _RejectedRequest(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def _headers_to_dict(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _media_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


async def _send_json(send: Send, status_code: int, error_code: str, message: str) -> None:
    body = json.dumps(
        {"success": False, "error_code": error_code, "message": message},
        separators=(",", ":"),
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-content-type-options", b"nosniff"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestGuardMiddleware:
    """Rejects oversized or unsupported request bodies before FastAPI parses them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.max_body_bytes = settings.MAX_REQUEST_BODY_BYTES
        self.allowed_write_content_types = {
            value.strip().lower()
            for value in settings.ALLOWED_WRITE_CONTENT_TYPES.split(",")
            if value.strip()
        }

    def _validate_headers(self, method: str, headers: dict[str, str]) -> None:
        raw_content_length = headers.get("content-length")
        if raw_content_length:
            try:
                content_length = int(raw_content_length)
            except ValueError as exc:
                raise _RejectedRequest(400, "INVALID_CONTENT_LENGTH", "Content-Length inválido") from exc
            if content_length > self.max_body_bytes:
                raise _RejectedRequest(413, "REQUEST_TOO_LARGE", "El cuerpo del request supera el límite permitido")
        else:
            content_length = None

        if method not in WRITE_METHODS:
            return

        content_type = _media_type(headers.get("content-type"))
        has_declared_body = (content_length is not None and content_length > 0) or bool(headers.get("transfer-encoding"))
        if (has_declared_body or content_type) and content_type not in self.allowed_write_content_types:
            raise _RejectedRequest(415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type no permitido para escritura")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = _headers_to_dict(scope)
        response_started = False

        try:
            self._validate_headers(method, headers)
        except _RejectedRequest as exc:
            await _send_json(send, exc.status_code, exc.error_code, exc.message)
            return

        received = 0

        async def guarded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"") or b""
                if body and method in WRITE_METHODS:
                    content_type = _media_type(headers.get("content-type"))
                    if content_type not in self.allowed_write_content_types:
                        raise _RejectedRequest(415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type no permitido para escritura")
                received += len(body)
                if received > self.max_body_bytes:
                    raise _RejectedRequest(413, "REQUEST_TOO_LARGE", "El cuerpo del request supera el límite permitido")
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _RejectedRequest as exc:
            if response_started:
                raise
            await _send_json(send, exc.status_code, exc.error_code, exc.message)


class SecurityHeadersMiddleware:
    """Adds defensive API response headers consistently from the backend."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _append_if_missing(headers: list[tuple[bytes, bytes]], key: bytes, value: bytes) -> None:
        key_lower = key.lower()
        if not any(existing_key.lower() == key_lower for existing_key, _ in headers):
            headers.append((key, value))

    def _security_headers(self, path: str) -> Iterable[tuple[bytes, bytes]]:
        yield b"x-content-type-options", b"nosniff"
        yield b"x-frame-options", b"DENY"
        yield b"referrer-policy", b"strict-origin-when-cross-origin"
        yield b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"
        yield b"x-permitted-cross-domain-policies", b"none"
        
        if settings.ENV == Environment.DEVELOPMENT:
            yield b"cross-origin-opener-policy", b"unsafe-none"
            yield b"cross-origin-resource-policy", b"cross-origin"
        else:
            yield b"cross-origin-opener-policy", b"same-origin"
            # The API is intentionally consumed from a different site.
            yield b"cross-origin-resource-policy", b"cross-origin"
            
        yield b"cache-control", b"no-store"
        yield b"pragma", b"no-cache"
        if settings.ENV == Environment.PRODUCTION:
            yield b"strict-transport-security", b"max-age=31536000; includeSubDomains"
            if not path.startswith(("/docs", "/redoc", "/openapi.json")):
                yield b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for key, value in self._security_headers(path):
                    self._append_if_missing(headers, key, value)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
