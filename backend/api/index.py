import json
import os
import re
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_ALLOWED_ORIGINS = {
    "https://shifty-frontend.mart-nez-sci-1390.chatgpt-team.site",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

REQUIRED_ENV_KEYS = {
    "ENV",
    "SECRET_KEY",
    "FIELD_ENCRYPTION_KEY",
    "CRON_SECRET",
    "DATABASE_URL",
    "REDIS_URL",
    "FRONTEND_URL",
    "PUBLIC_API_URL",
    "CORS_ORIGINS",
    "COOKIE_SECURE",
    "EXPOSE_API_DOCS",
    "ALLOW_PUBLIC_REGISTRATION",
    "RATE_LIMIT_ENABLED",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "EMAILS_FROM_EMAIL",
}


def _allowed_origins() -> set[str]:
    configured = os.getenv("CORS_ORIGINS", "")
    return {
        origin.strip()
        for origin in configured.split(",")
        if origin.strip()
    } or DEFAULT_ALLOWED_ORIGINS


def _cors_headers(scope: dict) -> list[tuple[bytes, bytes]]:
    request_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    origin = request_headers.get("origin", "")
    response_headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"cache-control", b"no-store"),
    ]
    if origin in _allowed_origins():
        response_headers.extend(
            [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-credentials", b"true"),
                (b"vary", b"Origin"),
            ]
        )
    return response_headers


def _sanitize_error(value: str) -> str:
    value = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s]+", r"\1[redacted]", value)
    value = re.sub(r"(?i)(secret|token|password|pass|key)=([^\s,;]+)", r"\1=[redacted]", value)
    return value[:2000]


def _missing_env_keys() -> list[str]:
    return sorted(key for key in REQUIRED_ENV_KEYS if not os.getenv(key))


def _error_app(error_code: str, message: str, detail: str):
    async def app(scope, receive, send):
        if scope["type"] != "http":
            await send({"type": "lifespan.startup.complete"})
            return

        headers = _cors_headers(scope)
        method = str(scope.get("method", "GET")).upper()
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
                "error_code": error_code,
                "message": message,
                "detail": detail,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send({"type": "http.response.start", "status": 503, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return app


missing_env_keys = _missing_env_keys()
if missing_env_keys:
    app = _error_app(
        "BACKEND_ENV_MISSING",
        "Backend production environment is incomplete.",
        "Missing environment variables: " + ", ".join(missing_env_keys),
    )
else:
    try:
        from main import app
    except Exception as exc:
        app = _error_app(
            "BACKEND_BOOT_FAILED",
            "Backend configuration failed during startup.",
            _sanitize_error(str(exc)),
        )
