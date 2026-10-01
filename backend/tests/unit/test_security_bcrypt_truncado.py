"""Contrato del recorte a 72 bytes de `core.security` frente a bcrypt 5.

2026-10-01: bcrypt 5.0.0 levanta ValueError con mas de 72 bytes en hashpw y
checkpw (las versiones 4.x truncaban en silencio). El recorte de security.py
evita que el login de contrasenas largas falle: este test lo fija para que una
version futura de la libreria o un cambio en security.py no lo rompa sin aviso.
"""

import pytest

from core.security import hash_password, verify_password

ASCII_LARGA = "a" * 100
# 128 caracteres de 2 bytes cada uno en UTF-8: 256 bytes, muy por encima de 72.
TILDES_LARGA = "áéíóúñüÁ" * 16


@pytest.mark.parametrize("password", [ASCII_LARGA, TILDES_LARGA])
def test_contrasena_de_mas_de_72_bytes_no_levanta_y_verifica(password: str) -> None:
    assert len(password.encode("utf-8")) > 72

    hashed = hash_password(password)

    assert hashed.startswith("$2b$")
    assert verify_password(password, hashed) is True


@pytest.mark.parametrize("password", [ASCII_LARGA, TILDES_LARGA])
def test_la_contrasena_recortada_a_72_bytes_tambien_verifica(password: str) -> None:
    hashed = hash_password(password)
    recortada = password.encode("utf-8")[:72].decode("utf-8", errors="ignore")

    assert verify_password(recortada, hashed) is True


def test_una_distinta_en_los_primeros_72_bytes_no_verifica() -> None:
    hashed = hash_password(ASCII_LARGA)
    distinta = "b" + ASCII_LARGA[1:]

    assert verify_password(distinta, hashed) is False
