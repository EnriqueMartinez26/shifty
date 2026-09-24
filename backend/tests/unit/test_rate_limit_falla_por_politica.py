"""Con Redis caido, el rate limit falla cerrado SOLO donde protege de verdad.

F1-09 (plan de rendimiento, R9-02, decision 9 del dueno, 2026-09-24).
Sintoma: con ``RATE_LIMIT_FAIL_CLOSED`` (obligatorio en produccion, regla 17)
un Redis caido o lleno devolvia 503 en TODA la API: health checks, el webhook
de Mercado Pago, la vitrina publica y el panel. Redis era punto unico de
falla del servicio entero.

Ahora el flag significa "cerrado" solo para las politicas que frenan fuerza
bruta o abuso anonimo de escritura: ``auth``, ``public-write`` y ``otp`` (el
presupuesto de OTP y el lockout de login viven en sus servicios y siguen
leyendo el flag). ``public-read``, ``global`` (panel, ops y el webhook, que
tiene HMAC + ventana + idempotencia) fallan ABIERTO, con un warning y un
aviso a Sentry acotado a uno por minuto.
"""

from __future__ import annotations

import ast
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request
from structlog.testing import capture_logs

import core.rate_limit as rate_limit
from core.config import settings
from core.exceptions import AppException

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def redis_caido(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)

    async def roto(*_args: object, **_kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", roto)
    avisos: list[str] = []
    monkeypatch.setattr(
        rate_limit, "_report_fail_open", lambda policy: avisos.append(policy)
    )
    return avisos


async def _por_el_middleware(method: str, path: str) -> tuple[int, bool]:
    """(status, si la app interna corrio)."""
    corrio = False
    enviados: list[MutableMapping[str, Any]] = []

    async def app(_scope: Any, _receive: Any, send: Any) -> None:
        nonlocal corrio
        corrio = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        enviados.append(message)

    await rate_limit.RedisRateLimitMiddleware(app)(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 1),
        },
        receive,
        send,
    )
    return int(enviados[0]["status"]), corrio


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "politica"),
    [
        ("GET", "/public/availability", "public-read"),
        ("GET", "/public/stores/mi-tienda", "public-read"),
        ("GET", "/ops/health/ready", "global"),
        ("GET", "/appointments/day", "global"),
        ("POST", "/payments/webhooks/mercadopago", "global"),
    ],
)
async def test_middleware_falla_abierto_en_lectura_global_y_webhook(
    redis_caido: list[str], method: str, path: str, politica: str
) -> None:
    with capture_logs() as eventos:
        status, corrio = await _por_el_middleware(method, path)

    assert (status, corrio) == (200, True)
    assert redis_caido == [politica], "fallo abierto sin aviso a Sentry"
    aviso = next(e for e in eventos if e["event"] == "rate_limit_fail_open")
    assert aviso["policy"] == politica
    assert aviso["log_level"] == "warning"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/auth/login"),
        ("POST", "/auth/refresh"),
        ("POST", "/public/appointments"),
        ("POST", "/public/otp/request"),
    ],
)
async def test_middleware_falla_cerrado_en_auth_y_escrituras_publicas(
    redis_caido: list[str], method: str, path: str
) -> None:
    status, corrio = await _por_el_middleware(method, path)

    assert (status, corrio) == (503, False)
    assert redis_caido == []


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/public/x",
            "headers": [],
            "client": ("127.0.0.1", 1),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "public:deposit:preview",
        "public:payment:status",
        "public:client:appointments",
        "public:waitlist:mine",
    ],
)
async def test_enforce_falla_abierto_en_lecturas_publicas(
    redis_caido: list[str], action: str
) -> None:
    await rate_limit.enforce_rate_limit(_request(), action, 5)

    assert redis_caido == ["public-read"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "auth:login",
        "auth:forgot-password",
        "public:otp:request",
        "public:otp:verify",
        "public:booking:create",
        "public:client:cancel",
        "public:waitlist:join",
        "accion:que:nadie:clasifico",
    ],
)
async def test_enforce_falla_cerrado_en_fuerza_bruta_escrituras_y_lo_desconocido(
    redis_caido: list[str], action: str
) -> None:
    with pytest.raises(AppException) as exc_info:
        await rate_limit.enforce_rate_limit(_request(), action, 5)

    assert exc_info.value.http_status == 503
    assert exc_info.value.error_code == "RATE_LIMIT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_sin_el_flag_todo_falla_abierto_como_antes(
    redis_caido: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)

    await rate_limit.enforce_rate_limit(_request(), "auth:login", 5)
    status, corrio = await _por_el_middleware("POST", "/auth/login")

    assert (status, corrio) == (200, True)


def _acciones_en_el_codigo() -> set[str]:
    acciones: set[str] = set()
    for archivo in (BACKEND / "modules").rglob("*.py"):
        tree = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(tree):
            if (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "enforce_rate_limit"
                and len(nodo.args) >= 2
                and isinstance(nodo.args[1], ast.Constant)
            ):
                acciones.add(str(nodo.args[1].value))
    return acciones


def test_toda_accion_de_enforce_rate_limit_tiene_politica_declarada() -> None:
    acciones = _acciones_en_el_codigo()

    assert acciones, "el escaneo no encontro llamadas a enforce_rate_limit"
    sin_politica = sorted(acciones - set(rate_limit.ACTION_POLICIES))
    assert sin_politica == [], (
        f"acciones sin politica declarada en core/rate_limit.py: {sin_politica}"
    )


def test_el_aviso_a_sentry_se_acota_a_uno_por_intervalo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sentry_sdk

    migas: list[dict[str, Any]] = []
    eventos: list[str] = []
    monkeypatch.setattr(sentry_sdk, "add_breadcrumb", lambda **kw: migas.append(kw))
    monkeypatch.setattr(
        sentry_sdk, "capture_message", lambda msg, **_kw: eventos.append(msg)
    )
    monkeypatch.setattr(rate_limit, "_last_fail_open_report", float("-inf"))

    for _ in range(3):
        rate_limit._report_fail_open("global")

    assert len(migas) == 3
    assert eventos == ["rate_limit_fail_open"]
