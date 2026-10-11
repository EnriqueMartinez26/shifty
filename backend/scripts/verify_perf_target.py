"""Fail-closed preflight for the performance-acceptance staging target."""

from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

HEALTH_PATH = "/api/ops/health/ready"
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


def _parse_https_url(value: str, *, allow_api_path: bool) -> tuple[str, int | None]:
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
        raise TargetCheckError("La configuración del destino no es válida.") from None

    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or "@" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
    ):
        raise TargetCheckError("La configuración del destino no es válida.")

    if allow_api_path:
        if parsed.path not in ("/api", "/api/"):
            raise TargetCheckError("La configuración del destino no es válida.")
    elif parsed.path not in ("", "/"):
        raise TargetCheckError("El origen aprobado no es válido.")

    return _normalized_host(parsed.hostname), port


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
