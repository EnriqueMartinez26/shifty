from collections.abc import Mapping
import re
from typing import Any

PUBLIC_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$"
SAFE_FILENAME_PREFIX_PATTERN = r"^[A-Za-z0-9_-]{3,50}$"

_FORBIDDEN_URL_PREFIXES = ("data:", "javascript:", "vbscript:", "file:")
_HTTP_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def reject_unsafe_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered.startswith(_FORBIDDEN_URL_PREFIXES):
        raise ValueError(
            "No se permiten URLs embebidas, data URLs ni esquemas inseguros"
        )
    if not _HTTP_URL_PATTERN.match(normalized):
        raise ValueError("La URL debe usar http o https")
    return normalized


def reject_control_chars(value: str | None) -> str | None:
    if value is None:
        return None
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise ValueError("El texto contiene caracteres de control no permitidos")
    return value


def reject_payload_control_chars(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return reject_control_chars(value)
    if isinstance(value, Mapping):
        return {
            reject_payload_control_chars(key): reject_payload_control_chars(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [reject_payload_control_chars(item) for item in value]
    if isinstance(value, tuple):
        return tuple(reject_payload_control_chars(item) for item in value)
    if isinstance(value, set):
        return {reject_payload_control_chars(item) for item in value}
    return value
