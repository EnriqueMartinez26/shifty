"""Un solo criterio para el nombre de un cliente en el reporte, y sin telefono.

2026-09-18, hallazgo B5-18: ``reports/service.py`` tenia dos helpers con
reglas distintas. ``top_clients`` y la lista de turnos usaban
``_report_client_name`` (nombre completo, si no email, si no el snapshot del
turno); ``top_debtors`` usaba ``_user_display_name`` (nombre, email y despues
el TELEFONO). Un deudor sin nombre ni email aparecia en el reporte con su
numero de telefono (PII que el resto del reporte no expone) y el mismo
cliente podia salir con dos nombres distintos en la misma respuesta.

La regla que queda es la del panel (``dashboard/service.py``:
``client.full_name or client.email``), que es tambien la de ``top_clients``:
nombre completo, si no email, si no el snapshot del turno cuando lo hay, y
como ultimo recurso el ``client_id``. El telefono nunca es un nombre.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.reports.service import ReportService
from modules.users.model import User, UserRole

TELEFONO = "+5491155550000"


def _cliente(**campos: Any) -> User:
    datos: dict[str, Any] = {
        "email": "",
        "hashed_password": "x",
        "role": UserRole.CLIENT,
        "store_id": "store-1",
        "phone": TELEFONO,
    }
    datos.update(campos)
    return User(**datos)


async def _top_deudores(filas: list[tuple[str, Decimal, User | None]]) -> list[str]:
    llamadas = iter(
        [
            SimpleNamespace(one=lambda: (len(filas), sum(f[1] for f in filas))),
            SimpleNamespace(all=lambda: filas),
        ]
    )

    async def fake_execute(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return next(llamadas)

    service = ReportService(
        db=cast(AsyncSession, SimpleNamespace(execute=fake_execute)),
        store_id="store-1",
    )
    resumen = await service._build_debt_summary()
    return [deudor.client_name for deudor in resumen.top_debtors]


@pytest.mark.asyncio
async def test_un_deudor_sin_nombre_ni_email_no_se_muestra_por_su_telefono() -> None:
    nombres = await _top_deudores(
        [("cli-sin-nombre", Decimal("300"), _cliente())],
    )
    assert TELEFONO not in nombres
    assert nombres == ["cli-sin-nombre"]


@pytest.mark.asyncio
async def test_los_deudores_siguen_la_regla_del_panel() -> None:
    nombres = await _top_deudores(
        [
            ("cli-1", Decimal("300"), _cliente(first_name="Ana", last_name="Paz")),
            ("cli-2", Decimal("200"), _cliente(email="beto@test.com")),
            ("cli-3", Decimal("100"), None),
        ],
    )
    assert nombres == ["Ana Paz", "beto@test.com", "cli-3"]
