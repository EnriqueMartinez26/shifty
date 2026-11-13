"""Clave de IP del rate limit: IPv6 por su /64, IPv4 por direccion (#277).

2026-11-02. Sintoma: una conexion IPv6 trae un /64 entero, y el limitador
contaba por direccion exacta: rotando direcciones dentro del prefijo, un
cliente evadia todo limite por IP (el cupo diario de reservas, `public-write`,
el OTP). Ahora la clave de una IPv6 es su /64; una IPv4 sigue siendo la
direccion, y una IPv4 mapeada (``::ffff:a.b.c.d``) cuenta como esa IPv4, no
como el /64 ``::ffff:0:0`` que comparten todas. La IP del request
(``client_ip_from_request``) no cambia: la auditoria de terminos la sigue
recibiendo exacta.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import pytest
from pytest import MonkeyPatch
from starlette.requests import Request

import core.rate_limit as rate_limit
from core.config import settings


@pytest.mark.parametrize(
    ("ip", "clave"),
    [
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:DB8:0001:0002:0:0:0:ff", "2001:db8:1:2::/64"),
        ("::1", "::/64"),
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("::ffff:cb00:7107", "203.0.113.7"),
        ("unknown", "unknown"),
        ("no-es-una-ip", "no-es-una-ip"),
    ],
)
def test_la_clave_agrupa_ipv6_por_su_64(ip: str, clave: str) -> None:
    assert rate_limit.rate_limit_ip_key(ip) == clave


def test_el_mismo_64_comparte_clave_y_otro_64_no() -> None:
    clave = rate_limit.rate_limit_ip_key
    assert clave("2001:db8:1:2::a") == clave("2001:db8:1:2:ffff::b")
    assert clave("2001:db8:1:2::a") != clave("2001:db8:1:3::a")
    # Dos IPv4 mapeadas distintas no se juntan en ::ffff:0:0/64.
    assert clave("::ffff:198.51.100.1") != clave("::ffff:198.51.100.2")


def _headers(**headers: str) -> dict[str, str]:
    return {nombre.replace("_", "-"): valor for nombre, valor in headers.items()}


def test_la_ip_del_request_sigue_siendo_el_ultimo_salto(
    monkeypatch: MonkeyPatch,
) -> None:
    # El primer elemento de X-Forwarded-For lo elige el cliente; el ultimo lo
    # escribe nuestro nginx. La IP del request no se agrupa (la auditoria la
    # recibe exacta).
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    xff = _headers(x_forwarded_for="198.51.100.1, 2001:db8:1:2::77")
    assert rate_limit._client_ip(xff, "10.0.0.1") == "2001:db8:1:2::77"


def test_un_header_falso_no_elige_la_ip(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    # Un ultimo salto que no es IP se descarta y vale X-Real-IP.
    falso = _headers(x_forwarded_for="2001:db8::1, basura", x_real_ip="203.0.113.9")
    assert rate_limit._client_ip(falso, "10.0.0.1") == "203.0.113.9"
    # Sin ninguna IP valida, la del socket.
    sin_ip = _headers(x_forwarded_for="2001:db8::/64", x_real_ip="no-es-ip")
    assert rate_limit._client_ip(sin_ip, "10.0.0.1") == "10.0.0.1"
    # Sin confiar en el proxy, los headers no cuentan.
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    otro = _headers(x_forwarded_for="2001:db8::1", x_real_ip="2001:db8::2")
    assert rate_limit._client_ip(otro, "10.0.0.1") == "10.0.0.1"


def _request(xff: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/public/appointments",
            "headers": [(b"x-forwarded-for", xff.encode("latin-1"))],
            "client": ("172.16.1.1", 12345),
        }
    )


def _registrar_cubetas(monkeypatch: MonkeyPatch) -> list[str]:
    identificadores: list[str] = []

    async def registrar(identifier: str, *_args: Any, **_kwargs: Any) -> None:
        identificadores.append(identifier)
        return None

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(rate_limit, "_hit_rate_limit", registrar)
    return identificadores


@pytest.mark.asyncio
async def test_enforce_rate_limit_cuenta_por_el_64(monkeypatch: MonkeyPatch) -> None:
    cubetas = _registrar_cubetas(monkeypatch)
    for ip in (
        "2001:db8:1:2::a",
        "2001:db8:1:2::b",
        "2001:db8:1:3::a",
        "203.0.113.7",
        "::ffff:203.0.113.7",
    ):
        await rate_limit.enforce_rate_limit(_request(ip), "public:booking:create", 5)

    assert cubetas == [
        "ip:2001:db8:1:2::/64",
        "ip:2001:db8:1:2::/64",
        "ip:2001:db8:1:3::/64",
        "ip:203.0.113.7",
        "ip:203.0.113.7",
    ]


@pytest.mark.asyncio
async def test_el_middleware_cuenta_por_el_64(monkeypatch: MonkeyPatch) -> None:
    cubetas = _registrar_cubetas(monkeypatch)
    llamadas: list[str] = []

    async def app(scope: Any, _receive: Any, _send: Any) -> None:
        llamadas.append(scope["path"])

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: MutableMapping[str, Any]) -> None:
        return None

    middleware = rate_limit.RedisRateLimitMiddleware(app)
    for ip in ("2001:db8:1:2::a", "2001:db8:1:2::b", "198.51.100.4"):
        await middleware(
            {
                "type": "http",
                "method": "GET",
                "path": "/public/availability",
                "headers": [(b"x-forwarded-for", ip.encode("latin-1"))],
                "client": ("172.16.1.1", 12345),
            },
            receive,
            send,
        )

    assert cubetas == ["2001:db8:1:2::/64", "2001:db8:1:2::/64", "198.51.100.4"]
    assert len(llamadas) == 3
