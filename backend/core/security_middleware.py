import json
from collections import deque
from typing import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import Environment, settings


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Rutas que aceptan multipart (subida de imagenes de tienda) con su propio
# limite de tamano. El path que ve el ASGI NO trae el prefijo /api (lo reescribe
# nginx). Van con Bearer, no cookie: no alcanzables por CSRF de formulario.
UPLOAD_PATHS = ("/stores/me/media",)
UPLOAD_CONTENT_TYPES = {"multipart/form-data"}

# SEG-03: Postgres no acepta NUL (U+0000) en un parametro de texto (SQLSTATE
# 22021) y el error subia como 500. Se rechaza aca, antes de cualquier router,
# para que ningun campo (body, query o path) pueda olvidarlo.
_JSON_NUL_ESCAPE = b"\\u0000"
_BACKSLASH = 0x5C
NUL_REJECTED_MESSAGE = "Error de validación en los datos enviados."


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


def _is_json(content_type: str) -> bool:
    return content_type == "application/json" or content_type.endswith("+json")


def contains_json_nul(data: bytes) -> bool:
    r"""True si el JSON crudo trae un NUL, como byte o como escape ``\u0000``.

    Un ``\u0000`` es escape solo si lo precede una cantidad impar de barras:
    ``"\\u0000"`` es una barra literal seguida de ``u0000``. Lineal: las
    corridas de barras de dos coincidencias no se solapan.
    """
    if b"\x00" in data:
        return True
    found = data.find(_JSON_NUL_ESCAPE)
    while found != -1:
        index = found
        while index >= 0 and data[index] == _BACKSLASH:
            index -= 1
        if (found - index) % 2 == 1:
            return True
        found = data.find(_JSON_NUL_ESCAPE, found + 1)
    return False


def _url_has_nul(scope: Scope) -> bool:
    # ``path`` ya viene decodificado; el query es crudo y un ``%`` literal
    # viaja como ``%25``, asi que ``%00`` solo puede ser un NUL.
    query = bytes(scope.get("query_string", b""))
    return "\x00" in str(scope.get("path", "")) or b"%00" in query or b"\x00" in query


async def _send_json(
    send: Send, status_code: int, error_code: str, message: str
) -> None:
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


async def _read_body(receive: Receive) -> list[Message]:
    messages: list[Message] = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request" or not message.get("more_body", False):
            return messages


def _replay(messages: list[Message], receive: Receive) -> Receive:
    pending = deque(messages)

    async def replay_receive() -> Message:
        if pending:
            return pending.popleft()
        return await receive()

    return replay_receive


class RequestGuardMiddleware:
    """Rejects oversized or unsupported request bodies before FastAPI parses them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.max_body_bytes = settings.MAX_REQUEST_BODY_BYTES
        self.max_upload_bytes = settings.MAX_UPLOAD_BODY_BYTES
        self.allowed_write_content_types = {
            value.strip().lower()
            for value in settings.ALLOWED_WRITE_CONTENT_TYPES.split(",")
            if value.strip()
        }

    def _limits_for(self, path: str) -> tuple[int, set[str]]:
        if path in UPLOAD_PATHS:
            return self.max_upload_bytes, UPLOAD_CONTENT_TYPES
        return self.max_body_bytes, self.allowed_write_content_types

    def _validate_headers(
        self, method: str, headers: dict[str, str], path: str
    ) -> None:
        max_bytes, allowed_content_types = self._limits_for(path)
        raw_content_length = headers.get("content-length")
        if raw_content_length:
            try:
                content_length = int(raw_content_length)
            except ValueError as exc:
                raise _RejectedRequest(
                    400, "INVALID_CONTENT_LENGTH", "Content-Length inválido"
                ) from exc
            if content_length > max_bytes:
                raise _RejectedRequest(
                    413,
                    "REQUEST_TOO_LARGE",
                    "El cuerpo del request supera el límite permitido",
                )
        else:
            content_length = None

        if method not in WRITE_METHODS:
            return

        content_type = _media_type(headers.get("content-type"))
        has_declared_body = (content_length is not None and content_length > 0) or bool(
            headers.get("transfer-encoding")
        )
        if (
            has_declared_body or content_type
        ) and content_type not in allowed_content_types:
            raise _RejectedRequest(
                415,
                "UNSUPPORTED_MEDIA_TYPE",
                "Content-Type no permitido para escritura",
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = _headers_to_dict(scope)
        path = str(scope.get("path", ""))
        max_bytes, allowed_content_types = self._limits_for(path)
        response_started = False

        if _url_has_nul(scope):
            await _send_json(send, 422, "VALIDATION_ERROR", NUL_REJECTED_MESSAGE)
            return

        try:
            self._validate_headers(method, headers, path)
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
                    if content_type not in allowed_content_types:
                        raise _RejectedRequest(
                            415,
                            "UNSUPPORTED_MEDIA_TYPE",
                            "Content-Type no permitido para escritura",
                        )
                received += len(body)
                if received > max_bytes:
                    raise _RejectedRequest(
                        413,
                        "REQUEST_TOO_LARGE",
                        "El cuerpo del request supera el límite permitido",
                    )
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        app_receive: Receive = guarded_receive
        content_type = _media_type(headers.get("content-type"))
        if _is_json(content_type) and path not in UPLOAD_PATHS:
            # El body JSON se lee entero ANTES del router (ya tiene tope de
            # bytes): un error levantado desde receive() dentro de FastAPI
            # se convierte en 400 "error parsing the body".
            try:
                buffered = await _read_body(guarded_receive)
            except _RejectedRequest as exc:
                await _send_json(send, exc.status_code, exc.error_code, exc.message)
                return
            body = b"".join(
                message.get("body", b"") or b""
                for message in buffered
                if message["type"] == "http.request"
            )
            if contains_json_nul(body):
                await _send_json(send, 422, "VALIDATION_ERROR", NUL_REJECTED_MESSAGE)
                return
            app_receive = _replay(buffered, receive)

        try:
            await self.app(scope, app_receive, guarded_send)
        except _RejectedRequest as exc:
            if response_started:
                raise
            await _send_json(send, exc.status_code, exc.error_code, exc.message)


class SecurityHeadersMiddleware:
    """Adds defensive API response headers consistently from the backend."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _append_if_missing(
        headers: list[tuple[bytes, bytes]], key: bytes, value: bytes
    ) -> None:
        key_lower = key.lower()
        if not any(existing_key.lower() == key_lower for existing_key, _ in headers):
            headers.append((key, value))

    def _security_headers(self, path: str) -> Iterable[tuple[bytes, bytes]]:
        yield b"x-content-type-options", b"nosniff"
        yield b"x-frame-options", b"DENY"
        yield b"referrer-policy", b"strict-origin-when-cross-origin"
        yield (
            b"permissions-policy",
            b"camera=(), microphone=(), geolocation=(), payment=()",
        )
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
                yield (
                    b"content-security-policy",
                    b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Una ruta que fijo su propio Cache-Control (la imagen
                # inmutable, el catalogo publico) no lleva `pragma: no-cache`:
                # un cache HTTP/1.0 lo leeria como "revalidar siempre" (F1-27).
                route_cache = any(k.lower() == b"cache-control" for k, _ in headers)
                for key, value in self._security_headers(path):
                    if route_cache and key == b"pragma":
                        continue
                    self._append_if_missing(headers, key, value)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
