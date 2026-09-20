"""Cada consulta del panel lleva su predicado ``store_id`` (defensa en profundidad).

2026-09-20, hallazgo AUD2-B5-16: el docstring de ``DashboardRepository`` afirma
que "cada consulta lleva el predicado ``store_id`` de la tienda del request
aunque RLS ya filtre", pero ``accredited_revenue_between`` llevaba solo
``Appointment.store_id`` (por el join) y no ``Payment.store_id``. El
aislamiento se sostenia igual —el join pasa por un ``appointments`` ya
acotado—, pero era la unica capa de defensa en profundidad que faltaba, y
``modules/reports`` si la pone. CLAUDE.md §2: los filtros ``store_id`` son
defensa en profundidad y no se quita ninguno. Un docstring que promete mas de
lo que el codigo hace es lo que la proxima auditoria va a creer.

El resultado ya lo cubre ``test_reportes_aislamiento_por_tienda.py``; lo que
falta verificar es el predicado, asi que estos tests miran la sentencia.
"""

from datetime import datetime, timezone
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.dashboard.repository import DashboardRepository

TIENDA = "store-1"
DESDE = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
HASTA = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)


class _SesionEspia:
    """Captura la sentencia y devuelve un resultado vacio."""

    def __init__(self) -> None:
        self.sentencias: list[str] = []

    async def execute(self, statement: Any) -> Any:
        self.sentencias.append(str(statement.compile()))

        class _Resultado:
            @staticmethod
            def scalar() -> int:
                return 0

            @staticmethod
            def scalars() -> Any:
                return type("_Vacio", (), {"all": staticmethod(lambda: [])})()

            @staticmethod
            def all() -> list[Any]:
                return []

        return _Resultado()


@pytest.mark.asyncio
async def test_el_ingreso_del_panel_acota_tambien_la_tabla_de_pagos() -> None:
    espia = _SesionEspia()
    repo = DashboardRepository(cast(AsyncSession, espia), store_id=TIENDA)
    await repo.accredited_revenue_between(DESDE, HASTA)
    sentencia = espia.sentencias[0]
    assert "appointments.store_id" in sentencia
    assert "payments.store_id" in sentencia, "falta el predicado sobre payments"


@pytest.mark.asyncio
async def test_toda_consulta_del_panel_nombra_la_tienda() -> None:
    espia = _SesionEspia()
    repo = DashboardRepository(cast(AsyncSession, espia), store_id=TIENDA)
    await repo.count_active_between(DESDE, HASTA)
    await repo.count_pending(DESDE)
    await repo.booked_minutes_between(DESDE, HASTA)
    await repo.schedules_for_weekday(2)
    await repo.count_new_clients_since(DESDE)
    await repo.accredited_revenue_between(DESDE, HASTA)
    await repo.average_duration_between(DESDE, HASTA)
    await repo.upcoming(DESDE, 5)
    assert len(espia.sentencias) == 8
    for sentencia in espia.sentencias:
        assert ".store_id" in sentencia
