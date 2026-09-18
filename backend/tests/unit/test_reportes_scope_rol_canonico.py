"""El scope del reporte se decide por rol canonico, no por el literal legacy.

2026-09-18, hallazgo B5-07: ``_report_scope_for`` autorizaba con
``canonical_role`` (vocabulario ``professional``) pero acotaba al profesional
comparando ``str(user.role) == "staff"``. Hoy ``UserRole`` solo emite
``"staff"`` y funcionaba por coincidencia; el dia que el rol persistido pasara
a ``"professional"``, el usuario seguia pasando la autorizacion y caia en
``return None``: veia el reporte COMPLETO de la tienda, incluido el
``debt_summary``. Falla abierta.
"""

from types import SimpleNamespace
from typing import cast

import pytest

from modules.reports.router import _report_scope_for
from modules.users.model import User


def _usuario(role: str, *, is_global_admin: bool = False) -> User:
    return cast(
        User,
        SimpleNamespace(
            id="user-1",
            role=role,
            is_global_admin=is_global_admin,
            store_id="store-1",
        ),
    )


@pytest.mark.parametrize("role", ["staff", "professional"])
def test_profesional_queda_acotado_a_sus_turnos_con_cualquier_vocabulario(
    role: str,
) -> None:
    assert _report_scope_for(_usuario(role)) == "user-1"


@pytest.mark.parametrize("role", ["admin", "store_admin"])
def test_admin_de_tienda_ve_la_tienda_completa(role: str) -> None:
    assert _report_scope_for(_usuario(role)) is None


def test_superadmin_no_queda_acotado_aunque_su_rol_sea_staff() -> None:
    assert _report_scope_for(_usuario("staff", is_global_admin=True)) is None
