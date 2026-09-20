"""Nombre y apellido de un usuario: entrada hostil (regla 19).

2026-09-20, AUD2-B5-03: ``UserBase``/``UserUpdate`` eran los unicos schemas de
texto libre sin ``reject_control_chars`` (``staff``, ``services``, ``stores``,
``superadmin`` y ``public_api`` si lo tienen). Sintoma: un admin cargaba un
cliente con ``\\x00`` en el nombre desde ``/users`` y esos campos alimentan
``_report_client_name``, asi que el NUL terminaba en la planilla del reporte y
la rompia. Es la puerta de entrada del hallazgo; la limpieza del exportador es
la segunda capa.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from modules.users.schemas import UserCreate, UserUpdate

TEXTOS_HOSTILES = ["Ana\x00", "Ana‮b", "Ana​b", "Ana﻿b"]
CAMPOS = ["first_name", "last_name"]


@pytest.mark.parametrize("valor", TEXTOS_HOSTILES)
@pytest.mark.parametrize("campo", CAMPOS)
def test_el_alta_rechaza_caracteres_de_control(campo: str, valor: str) -> None:
    datos: dict[str, Any] = {
        "email": "ana@test.com",
        "password": "Contrasena-Larga-9",
        campo: valor,
    }
    with pytest.raises(ValidationError):
        UserCreate.model_validate(datos)


@pytest.mark.parametrize("valor", TEXTOS_HOSTILES)
@pytest.mark.parametrize("campo", CAMPOS)
def test_la_edicion_rechaza_caracteres_de_control(campo: str, valor: str) -> None:
    with pytest.raises(ValidationError):
        UserUpdate.model_validate({campo: valor})


def test_un_nombre_normal_sigue_pasando() -> None:
    usuario = UserUpdate.model_validate(
        {"first_name": "Ana María", "last_name": "Pérez Gómez"}
    )
    assert usuario.first_name == "Ana María"
    assert usuario.last_name == "Pérez Gómez"
