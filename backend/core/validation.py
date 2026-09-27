from collections.abc import Mapping
from datetime import date
import re
from typing import Annotated, Any

from pydantic import AfterValidator

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


# Invisibles que permiten spoofing visual (mostrar algo distinto a lo guardado),
# ataques de bidireccionalidad (Trojan Source) o romper el renderizado: bidi
# embeddings/overrides/isolates, zero-width y BOM.
_FORBIDDEN_UNICODE = frozenset(
    chr(cp)
    for cp in (
        0x200B,
        0x200C,
        0x200D,
        0x200E,
        0x200F,  # zero-width + LRM/RLM
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,  # bidi embeddings/overrides
        0x2066,
        0x2067,
        0x2068,
        0x2069,  # bidi isolates (Trojan Source)
        0xFEFF,  # BOM / zero-width no-break space
    )
)


def reject_control_chars(value: str | None) -> str | None:
    if value is None:
        return None
    for char in value:
        if (ord(char) < 32 and char not in "\t\n\r") or char in _FORBIDDEN_UNICODE:
            raise ValueError("El texto contiene caracteres de control no permitidos")
    return value


def _has_next_day(value: date) -> date:
    """Un dia de consulta se corta en ``local_day_start(dia + 1)``: el ultimo
    dia representable (9999-12-31) no tiene siguiente y desbordaba (500)."""
    if value >= date.max:
        raise ValueError("La fecha esta fuera de rango")
    return value


# Dia local de un filtro (agenda, busqueda, reportes): 422 si no tiene dia
# siguiente (revision de perf/f4-back, 2026-09-24).
LocalDay = Annotated[date, AfterValidator(_has_next_day)]


def _has_both_neighbors(value: date) -> date:
    """La grilla de disponibilidad mira tambien el dia anterior y el
    siguiente (turnos que cruzan la medianoche): el primer y el ultimo dia
    representables desbordaban (500)."""
    if value <= date.min or value >= date.max:
        raise ValueError("La fecha esta fuera de rango")
    return value


# Dia de la grilla de disponibilidad del panel.
GridDay = Annotated[date, AfterValidator(_has_both_neighbors)]


_PHONE_SEPARATORS = re.compile(r"[\s\-\(\)\+]")


def normalize_client_phone(value: str) -> str:
    """Telefono del cliente como lo guarda ``users.phone``: solo digitos.

    Es la identidad del cliente en la tienda (``uq_users_client_phone_per_store``):
    el portal y el alta del panel (FF-04) normalizan igual o el mismo cliente
    quedaria con dos fichas.
    """
    cleaned = _PHONE_SEPARATORS.sub("", value)
    if not cleaned.isdigit():
        raise ValueError(
            "El telefono solo puede contener digitos, espacios o los caracteres: + - ( )"
        )
    if len(cleaned) < 6:
        raise ValueError("El telefono debe tener al menos 6 digitos")
    return cleaned


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


# Claves mas usadas del mundo real (rankings de brechas publicas), normalizadas
# a minusculas. No pretende ser un corpus completo: corta lo que un atacante
# prueba primero en un password spraying. ASVS 2.1.7.
_PASSWORDS_PROHIBIDAS = {
    "123456789012",
    "contraseña123",
    "contrasena123",
    "password1234",
    "password12345",
    "passw0rd1234",
    "qwerty123456",
    "111111111111",
    "123456789abc",
    "abc123456789",
    "1234567890ab",
    "administrador1",
    "admin1234567",
    "shifty123456",
    "bienvenido123",
    "welcome12345",
    "iloveyou1234",
    "dragon123456",
    "futbol123456",
    "argentina123",
    "boca12345678",
    "river1234567",
}


def validate_password_strength(password: str) -> str:
    """Politica de contrasena para cuentas nuevas o cambiadas (ASVS 2.1).

    Piso de 12 caracteres (el largo es la defensa real), al menos una letra y
    un numero para cortar los casos triviales, y una denylist de claves
    quemadas en brechas. No se aplica al login para no invalidar contrasenas
    ya existentes.
    """
    if len(password) < 12:
        raise ValueError("La contrasena debe tener al menos 12 caracteres")
    if not any(c.isalpha() for c in password):
        raise ValueError("La contrasena debe incluir al menos una letra")
    if not any(c.isdigit() for c in password):
        raise ValueError("La contrasena debe incluir al menos un numero")
    if password.lower() in _PASSWORDS_PROHIBIDAS:
        raise ValueError("Esa contrasena es demasiado comun; elegi otra")
    return password
