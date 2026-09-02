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
