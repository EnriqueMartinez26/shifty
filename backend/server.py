import json
import os
import re


_DEFAULT_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://shifty-frontend.mart-nez-sci-1390.chatgpt-team.site",
}


def _allowed_origins() -> set[str]:
    configured = os.getenv("CORS_ORIGINS", "")
    return {
        origin.strip()
        for origin in configured.split(",")
        if origin.strip()
    } or _DEFAULT_ALLOWED_ORIGINS


def _cors_headers(scope: dict) -> list[tuple[bytes, bytes]]:
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    origin = headers.get("origin", "")
    allow_origin = origin if origin in _allowed_origins() else ""
    response_headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"cache-control", b"no-store"),
    ]
    if allow_origin:
        response_headers.extend(
            [
                (b"access-control-allow-origin", allow_origin.encode("latin-1")),
                (b"access-control-allow-credentials", b"true"),
                (b"vary", b"Origin"),
            ]
        )
    return response_headers


def _sanitize_error(value: str) -> str:
    value = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^\\s]+", r"\1[redacted]", value)
    value = re.sub(r"(?i)(secret|token|password|pass|key)=([^\\s,;]+)", r"\1=[redacted]", value)
    return value[:2000]


def _boot_error_app(exc: Exception):
    async def app(scope, receive, send):
        if scope["type"] != "http":
            await send({"type": "lifespan.startup.complete"})
            return

        method = str(scope.get("method", "GET")).upper()
        headers = _cors_headers(scope)

        if method == "OPTIONS":
            headers.extend(
                [
                    (b"access-control-allow-methods", b"DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"),
                    (b"access-control-allow-headers", b"*"),
                    (b"access-control-max-age", b"600"),
                ]
            )
            body = b"{}"
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        body = json.dumps(
            {
                "success": False,
                "error_code": "BACKEND_BOOT_FAILED",
                "message": "Backend configuration failed during startup.",
                "error_type": type(exc).__name__,
                "detail": _sanitize_error(str(exc)),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send({"type": "http.response.start", "status": 503, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return app


try:
    from main import app
except Exception as exc:
    app = _boot_error_app(exc)

