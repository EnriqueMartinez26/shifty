"""Fail-closed preflight for the performance-acceptance staging target."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

import httpx

HEALTH_PATH = "/api/ops/health/ready"
REQUEST_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 64 * 1024
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NUMERIC_HOST = re.compile(r"(?i)(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*\Z")


class TargetCheckError(Exception):
    """Safe, user-facing failure with no target or response data attached."""


def _prohibited_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
        or (
            mapped is not None
            and (
                mapped.is_loopback
                or mapped.is_unspecified
                or mapped.is_link_local
                or mapped.is_multicast
            )
        )
    )


def _normalized_host(host: str) -> str:
    if not host or "%" in host:
        raise TargetCheckError("El origen aprobado no es válido.")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(host):
            raise TargetCheckError("El origen aprobado no es válido.") from None
    else:
        if _prohibited_address(address):
            raise TargetCheckError("El origen aprobado no es válido.")
        return address.compressed.lower()

    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise TargetCheckError("El origen aprobado no es válido.") from None

    if (
        len(ascii_host) > 253
        or not ascii_host
        or ascii_host == "localhost"
        or ascii_host.endswith(".localhost")
    ):
        raise TargetCheckError("El origen aprobado no es válido.")

    # IDNA compatibility mapping can turn fullwidth characters into an IP or
    # localhost spelling. Apply the same address checks to the ASCII result.
    try:
        normalized_address = ipaddress.ip_address(ascii_host)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(ascii_host):
            raise TargetCheckError("El origen aprobado no es válido.") from None
    else:
        if _prohibited_address(normalized_address):
            raise TargetCheckError("El origen aprobado no es válido.")
        return normalized_address.compressed.lower()

    if any(not _DNS_LABEL.fullmatch(label) for label in ascii_host.split(".")):
        raise TargetCheckError("El origen aprobado no es válido.")
    return ascii_host


def _split_config_url(
    value: str, *, error_message: str
) -> tuple[SplitResult, int | None]:
    if (
        not value
        or value != value.strip()
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
        or "\\" in value
        or "?" in value
        or "#" in value
    ):
        raise TargetCheckError("La configuración del destino no es válida.")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise TargetCheckError(error_message) from None

    if (
        not parsed.netloc
        or parsed.hostname is None
        or "@" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or port == 0
    ):
        raise TargetCheckError(error_message)

    return parsed, port


def _parse_https_url(value: str, *, allow_api_path: bool) -> tuple[str, int | None]:
    error_message = (
        "La configuración del destino no es válida."
        if allow_api_path
        else "El origen aprobado no es válido."
    )
    parsed, port = _split_config_url(value, error_message=error_message)
    if parsed.scheme.lower() != "https":
        raise TargetCheckError(error_message)

    if allow_api_path:
        if parsed.path not in ("/api", "/api/"):
            raise TargetCheckError("La configuración del destino no es válida.")
    elif parsed.path not in ("", "/"):
        raise TargetCheckError("El origen aprobado no es válido.")

    hostname = parsed.hostname
    if hostname is None:
        raise TargetCheckError(error_message)
    return _normalized_host(hostname), port


def _raw_authority_host(netloc: str) -> str:
    """Return the host spelling as configured, preserving IPv6 brackets."""
    if netloc.startswith("["):
        closing = netloc.find("]")
        if closing < 0:
            return ""
        return netloc[: closing + 1]
    return netloc.split(":", 1)[0]


def _format_local_origin(host: str, port: int | None) -> str:
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != 80:
        authority = f"{authority}:{port}"
    return f"http://{authority}"


def canonical_target_url(api_url: str, allowed_origin: str | None = None) -> str:
    """Canonicalize a loopback URL or an approved remote API target.

    Local HTTP is limited to literal loopback authorities. The entrypoint
    verifier applies the explicit developer-only opt-in before use. Remote
    targets must use HTTPS and match the configured origin exactly.
    This helper is pure so synchronous callers such as Locust can use it
    without starting a network request or an asyncio/gevent interaction.
    """
    parsed, port = _split_config_url(
        api_url, error_message="La configuración del destino no es válida."
    )

    if parsed.scheme.lower() == "http":
        raw_host = _raw_authority_host(parsed.netloc)
        local_hosts = {
            "localhost": "localhost",
            "127.0.0.1": "127.0.0.1",
            "[::1]": "::1",
        }
        host = local_hosts.get(raw_host)
        if host is None or parsed.path not in ("", "/", "/api", "/api/"):
            raise TargetCheckError("La configuración del destino no es válida.")
        if allowed_origin:
            raise TargetCheckError(
                "El destino local no debe configurar un origen aprobado."
            )
        base = _format_local_origin(host, port)
        return f"{base}/api" if parsed.path in ("/api", "/api/") else base

    if parsed.scheme.lower() != "https":
        raise TargetCheckError("La configuración del destino no es válida.")
    if not allowed_origin:
        raise TargetCheckError("Faltan variables para validar el destino de staging.")

    host, remote_port = _parse_https_url(api_url, allow_api_path=True)
    approved = normalize_origin(allowed_origin)
    if _format_origin(host, remote_port) != approved:
        raise TargetCheckError("El destino no coincide con el origen aprobado.")
    return f"{approved}/api"


def _format_origin(host: str, port: int | None) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        authority = host
    else:
        authority = (
            f"[{address.compressed}]" if address.version == 6 else address.compressed
        )
    if port is not None and port != 443:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def normalize_origin(value: str) -> str:
    """Canonicalize an HTTPS origin; allow only an optional trailing slash."""
    host, port = _parse_https_url(value, allow_api_path=False)
    return _format_origin(host, port)


def build_health_url(staging_url: str, allowed_origin: str) -> str:
    """Require the exact approved origin and return its readiness URL."""
    host, port = _parse_https_url(staging_url, allow_api_path=True)
    approved = normalize_origin(allowed_origin)
    if _format_origin(host, port) != approved:
        raise TargetCheckError("El destino no coincide con el origen aprobado.")
    return f"{approved}{HEALTH_PATH}"


def validate_health_response(status: int, body: bytes) -> None:
    """Require HTTP 200 and the canonical staging readiness envelope."""
    if status != 200 or len(body) > MAX_RESPONSE_BYTES:
        raise TargetCheckError("La respuesta del endpoint de salud no es válida.")
    try:
        payload = json.loads(body)
    except UnicodeDecodeError, json.JSONDecodeError, TypeError, RecursionError:
        raise TargetCheckError(
            "La respuesta del endpoint de salud no es válida."
        ) from None
    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(payload.get("data"), dict)
        or payload["data"].get("environment") != "staging"
    ):
        raise TargetCheckError("El endpoint no confirmó un entorno de staging.")


async def _request_health(
    url: str, transport: httpx.AsyncBaseTransport | None
) -> tuple[int, bytes]:
    async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
            trust_env=False,
        ) as client:
            async with client.stream(
                "GET",
                url,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise TargetCheckError(
                            "La respuesta del endpoint de salud no es válida."
                        )
                    body.extend(chunk)
                return response.status_code, bytes(body)


def _probe_worker_command() -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--probe-health-stdin"]


def _run_probe_worker(url: str) -> None:
    try:
        result = subprocess.run(
            _probe_worker_command(),
            input=url,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        raise TargetCheckError("No se pudo consultar el endpoint de salud.") from None
    if result.returncode != 0:
        raise TargetCheckError("No se pudo consultar el endpoint de salud.")


def probe_health(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """GET readiness under a total deadline, with a capped body and no redirects."""
    if transport is None:
        _run_probe_worker(url)
        return
    try:
        status, body = asyncio.run(_request_health(url, transport))
    except TargetCheckError:
        raise
    except Exception:
        raise TargetCheckError("No se pudo consultar el endpoint de salud.") from None
    validate_health_response(status, body)


def verify_target_url(
    api_url: str,
    allowed_origin: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Validate a remote staging URL and return the canonical API base."""
    health_url = build_health_url(api_url, allowed_origin)
    probe_health(health_url, transport=transport)
    return f"{normalize_origin(allowed_origin)}/api"


def verify_target(
    environment: Mapping[str, str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Validate the target, requiring an opt-in for local developer runs."""
    variables = os.environ if environment is None else environment
    staging_url = variables.get("STAGING_URL", "")
    allowed_origin = variables.get("PERF_ALLOWED_ORIGIN", "")
    if not staging_url:
        raise TargetCheckError("Faltan variables para validar el destino de staging.")
    canonical_url = canonical_target_url(staging_url, allowed_origin)
    if canonical_url.startswith("http://"):
        if variables.get("GITHUB_ACTIONS", "").casefold() == "true":
            raise TargetCheckError(
                "El destino local no está permitido en GitHub Actions."
            )
        if variables.get("PERF_ALLOW_LOCAL_TARGET") != "true":
            raise TargetCheckError(
                "El destino local requiere PERF_ALLOW_LOCAL_TARGET=true."
            )
        return canonical_url
    if canonical_url.startswith("https://"):
        probe_health(
            build_health_url(canonical_url, allowed_origin), transport=transport
        )
    return canonical_url


def main(
    environment: Mapping[str, str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    try:
        verify_target(environment, transport=transport)
    except TargetCheckError as exc:
        print(f"Destino de staging rechazado: {exc}", file=sys.stderr)
        return 1
    print("Destino de staging validado.")
    return 0


def _probe_worker_main() -> int:
    try:
        url = sys.stdin.read(4096)
        status, body = asyncio.run(_request_health(url, None))
        validate_health_response(status, body)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe-health-stdin"]:
        raise SystemExit(_probe_worker_main())
    raise SystemExit(main())
