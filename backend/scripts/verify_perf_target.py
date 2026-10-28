"""Fail-closed validator for performance-test targets and staging preflight."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HEALTH_PATH = "/api/ops/health/ready"
REQUEST_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 64 * 1024
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NUMERIC_HOST = re.compile(r"(?i)(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*\Z")


class TargetCheckError(Exception):
    """Safe, user-facing failure with no target or response data attached."""


def _address_is_prohibited(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
        or (mapped is not None and mapped.is_loopback)
    )


def _normalized_host(host: str, *, allow_loopback: bool = False) -> str:
    if not host or "%" in host:
        raise TargetCheckError("El origen aprobado no es válido.")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(host):
            raise TargetCheckError("El origen aprobado no es válido.") from None
    else:
        if _address_is_prohibited(address) and not (
            allow_loopback and address.is_loopback
        ):
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

    # IDNA maps compatibility characters (for example fullwidth digits and
    # letters) to ASCII. Re-parse that result so an obfuscated address or a
    # localhost alias cannot bypass the checks applied to literal IP hosts.
    try:
        normalized_address = ipaddress.ip_address(ascii_host)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(ascii_host):
            raise TargetCheckError("El origen aprobado no es válido.") from None
    else:
        # Loopback is accepted only when the original URL contained a literal
        # IP recognized by ipaddress above; IDNA-mapped spellings are not a
        # local-rehearsal exception.
        if _address_is_prohibited(normalized_address):
            raise TargetCheckError("El origen aprobado no es válido.")
        return normalized_address.compressed.lower()

    labels = ascii_host.split(".")
    if any(not _DNS_LABEL.fullmatch(label) for label in labels):
        raise TargetCheckError("El origen aprobado no es válido.")
    return ascii_host


def _parse_url(
    value: str, *, schemes: tuple[str, ...], allow_api_path: bool
) -> tuple[str, str, int | None]:
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

    scheme = parsed.scheme.lower()
    if (
        scheme not in schemes
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

    host = _normalized_host(parsed.hostname, allow_loopback=scheme == "http")
    return scheme, host, port


def _format_origin(scheme: str, host: str, port: int | None) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        authority = host
    else:
        authority = (
            f"[{address.compressed}]" if address.version == 6 else address.compressed
        )

    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"
    return f"{scheme}://{authority}"


def _parse_https_url(value: str, *, allow_api_path: bool) -> tuple[str, int | None]:
    _, host, port = _parse_url(value, schemes=("https",), allow_api_path=allow_api_path)
    return host, port


def normalize_origin(value: str) -> str:
    """Return a canonical HTTPS origin; accept only an origin and optional slash."""
    host, port = _parse_https_url(value, allow_api_path=False)
    return _format_origin("https", host, port)


def build_health_url(staging_url: str, allowed_origin: str) -> str:
    """Validate the API base against the approved origin and build its probe URL."""
    _, staging_host, staging_port = _parse_url(
        staging_url, schemes=("https",), allow_api_path=True
    )
    approved = normalize_origin(allowed_origin)
    if _format_origin("https", staging_host, staging_port) != approved:
        raise TargetCheckError("El destino no coincide con el origen aprobado.")
    return f"{approved}{HEALTH_PATH}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _new_opener() -> Any:
    return build_opener(_NoRedirect())


def validate_health_response(status: int, body: bytes) -> None:
    """Require HTTP 200 and the canonical success envelope for staging."""
    if status != 200:
        raise TargetCheckError("El endpoint de salud no respondió HTTP 200.")
    if len(body) > MAX_RESPONSE_BYTES:
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


def probe_health(url: str, *, opener: Any | None = None) -> None:
    """Perform a non-redirecting bounded GET and validate its canonical body."""
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    client = _new_opener() if opener is None else opener
    try:
        with client.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.getcode()
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except TargetCheckError:
        raise
    except Exception:
        # urllib exceptions can contain the full secret URL or response data.
        raise TargetCheckError("No se pudo consultar el endpoint de salud.") from None

    validate_health_response(status, body)


def verify_target_url(
    api_url: str,
    allowed_origin: str | None = None,
    *,
    allow_local: bool = False,
    opener: Any | None = None,
) -> str:
    """Validate and return the canonical API base an entrypoint must use.

    Plain HTTP is reserved for literal loopback IPs used by local rehearsals.
    Any remote target must match the HTTPS allowlist and pass the staging
    readiness probe before this function returns.
    """
    scheme, host, port = _parse_url(
        api_url, schemes=("https", "http"), allow_api_path=True
    )

    if scheme == "http":
        if not allow_local:
            raise TargetCheckError("El destino de staging debe usar HTTPS.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise TargetCheckError(
                "HTTP solo se permite para una IP local de loopback."
            ) from None
        if not address.is_loopback:
            raise TargetCheckError(
                "HTTP solo se permite para una IP local de loopback."
            )
        return f"{_format_origin('http', host, port)}/api"

    if not allowed_origin:
        raise TargetCheckError("Falta PERF_ALLOWED_ORIGIN para validar staging.")
    health_url = build_health_url(api_url, allowed_origin)
    probe_health(health_url, opener=opener)
    approved = normalize_origin(allowed_origin)
    return f"{approved}/api"


def verify_target(
    environment: Mapping[str, str] | None = None, *, opener: Any | None = None
) -> str:
    """Validate ``STAGING_URL`` strictly as remote HTTPS staging."""
    variables = os.environ if environment is None else environment
    staging_url = variables.get("STAGING_URL", "")
    if not staging_url:
        raise TargetCheckError("Falta STAGING_URL para validar el destino.")
    return verify_target_url(
        staging_url, variables.get("PERF_ALLOWED_ORIGIN"), opener=opener
    )


def main(
    environment: Mapping[str, str] | None = None, *, opener: Any | None = None
) -> int:
    try:
        verify_target(environment, opener=opener)
    except TargetCheckError as exc:
        print(f"Destino de rendimiento rechazado: {exc}", file=sys.stderr)
        return 1
    print("Destino de staging validado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
