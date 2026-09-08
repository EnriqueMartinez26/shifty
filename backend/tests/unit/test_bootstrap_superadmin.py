"""El bootstrap del primer superadmin valida el email como el login.

Regresion real: el script aceptaba cualquier string y el login usa EmailStr
(rechaza dominios reservados como .local). Se creaba un superadmin que jamas
podia entrar: plataforma sin superadmin operable.
"""

import pytest

from scripts.bootstrap_superadmin import validate_superadmin_email


@pytest.mark.parametrize(
    "raw",
    [
        "root@shifty.local",
        "admin@localhost",
        "sin-arroba",
        "a@b",
        "root@shifty.invalid",
    ],
)
def test_rechaza_emails_que_el_login_no_aceptaria(raw: str) -> None:
    with pytest.raises(RuntimeError, match="SUPERADMIN_EMAIL invalido"):
        validate_superadmin_email(raw)


def test_normaliza_a_minusculas_y_acepta_dominios_reales() -> None:
    assert validate_superadmin_email("  Root@Shifty-App.COM ") == "root@shifty-app.com"
