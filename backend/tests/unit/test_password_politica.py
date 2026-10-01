"""Politica de contrasena al fijarla (D-20261001-01, 2026-10-01).

Piso 6, techo 64 caracteres y 72 bytes en UTF-8 (lo que bcrypt realmente
mira): pasar los 72 bytes se rechaza con un mensaje claro en vez de truncar en
silencio. Letra + numero y la denylist siguen igual. Una sola fuente de los
numeros (``core.validation``) y los schemas la importan.

El login queda afuera: ``LoginRequest.password`` y
``ChangePasswordRequest.current_password`` siguen en 1 a 128.
"""

from typing import Any

import pytest

from core.validation import (
    PASSWORD_MAX_BYTES,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    _PASSWORDS_PROHIBIDAS,
    validate_password_strength,
)
from modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
)
from modules.superadmin.schemas import StoreAdminCreate, UserGlobalUpdate
from modules.users.schemas import UserCreate, UserUpdate
from scripts.bootstrap_superadmin import validate_superadmin_password


def test_los_numeros_de_la_politica_son_los_de_la_decision() -> None:
    assert PASSWORD_MIN_LENGTH == 6
    assert PASSWORD_MAX_LENGTH == 64
    assert PASSWORD_MAX_BYTES == 72


@pytest.mark.parametrize(
    "password",
    [
        "abcde1",
        "a" * 63 + "1",
        "á" * 35 + "12",  # 37 caracteres, exactamente 72 bytes
        "Password123!",
    ],
)
def test_acepta_lo_que_esta_dentro_de_los_limites_y_lo_devuelve_intacto(
    password: str,
) -> None:
    assert validate_password_strength(password) == password


@pytest.mark.parametrize("password", ["", "a", "abc12", "ab1"])
def test_rechaza_menos_de_6_caracteres(password: str) -> None:
    with pytest.raises(ValueError, match="al menos 6 caracteres"):
        validate_password_strength(password)


@pytest.mark.parametrize(
    "password",
    [
        "á" * 36 + "1",  # 73 bytes
        "á" * 36 + "12",  # 74 bytes
        "á" * 37,  # 74 bytes y ademas sin numero: el tope de bytes va primero
        "á" * 63 + "1",  # 64 caracteres de 2 bytes: 127 bytes
    ],
)
def test_rechaza_mas_de_72_bytes_con_un_mensaje_claro_sin_truncar(
    password: str,
) -> None:
    assert len(password.encode("utf-8")) > 72
    with pytest.raises(ValueError, match="72 bytes"):
        validate_password_strength(password)


@pytest.mark.parametrize("password", ["a" * 64 + "1", "a" * 100 + "1", "1" + "a" * 200])
def test_rechaza_mas_de_64_caracteres_aunque_no_pasen_de_72_bytes(
    password: str,
) -> None:
    # El techo de caracteres tambien vive en el validador: el bootstrap del
    # superadmin no pasa por un schema de Pydantic.
    with pytest.raises(ValueError, match="64 caracteres"):
        validate_password_strength(password)


def test_sigue_exigiendo_letra_y_numero() -> None:
    with pytest.raises(ValueError, match="una letra"):
        validate_password_strength("12345678")
    with pytest.raises(ValueError, match="un numero"):
        validate_password_strength("abcdefgh")


def test_toda_clave_de_la_denylist_con_letra_y_numero_sigue_rechazada() -> None:
    # La denylist no cambia (22 entradas, todas de 12 caracteres o mas): con el
    # piso en 6 siguen siendo alcanzables y las que pasan letra + numero solo
    # las corta la lista.
    alcanzables = [
        clave
        for clave in _PASSWORDS_PROHIBIDAS
        if any(c.isalpha() for c in clave) and any(c.isdigit() for c in clave)
    ]
    assert alcanzables, "la denylist ya no tiene claves con letra y numero"
    for clave in alcanzables:
        for variante in (clave, clave.upper(), clave.capitalize()):
            with pytest.raises(ValueError, match="demasiado comun"):
                validate_password_strength(variante)


def _limites_del_campo(modelo: type[Any], campo: str) -> tuple[int | None, int | None]:
    propiedad = modelo.model_json_schema()["properties"][campo]
    if "anyOf" in propiedad:  # campo opcional: la rama string lleva los topes
        propiedad = next(r for r in propiedad["anyOf"] if r.get("type") == "string")
    return propiedad.get("minLength"), propiedad.get("maxLength")


@pytest.mark.parametrize(
    ("modelo", "campo"),
    [
        (ResetPasswordRequest, "new_password"),
        (ChangePasswordRequest, "new_password"),
        (UserCreate, "password"),
        (UserUpdate, "password"),
        (StoreAdminCreate, "password"),
        (UserGlobalUpdate, "password"),
    ],
)
def test_los_seis_campos_que_fijan_una_clave_usan_los_topes_de_la_politica(
    modelo: type[Any], campo: str
) -> None:
    assert _limites_del_campo(modelo, campo) == (
        PASSWORD_MIN_LENGTH,
        PASSWORD_MAX_LENGTH,
    )


@pytest.mark.parametrize(
    ("modelo", "campo"),
    [
        (LoginRequest, "password"),
        (ChangePasswordRequest, "current_password"),
    ],
)
def test_el_login_y_la_clave_actual_siguen_de_1_a_128(
    modelo: type[Any], campo: str
) -> None:
    assert _limites_del_campo(modelo, campo) == (1, 128)


def test_el_bootstrap_del_superadmin_usa_la_misma_politica() -> None:
    assert validate_superadmin_password("abcde1") == "abcde1"
    assert validate_superadmin_password("a" * 63 + "1") == "a" * 63 + "1"
    for rechazada in (
        "abc12",
        "a" * 64 + "1",
        "á" * 36 + "12",
        "abcdefgh",
        "12345678",
        "password1234",
    ):
        with pytest.raises(RuntimeError, match="SUPERADMIN_PASSWORD invalida"):
            validate_superadmin_password(rechazada)
