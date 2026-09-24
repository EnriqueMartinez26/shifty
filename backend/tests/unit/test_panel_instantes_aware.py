"""El panel compara instantes AWARE contra ``timestamptz`` (regla 24).

2026-09-20, hallazgo AUD2-B5-07: ``DashboardRepository`` recibia los limites
aware en UTC (los arma ``local_day_start``, correcto) y les hacia
``.replace(tzinfo=None)`` antes de comparar. ``appointments.starts_at`` es
``DateTime(timezone=True)`` -> ``timestamptz`` en Postgres, y asyncpg codifica
un datetime naive con ``obj.astimezone(utc)``, que interpreta el naive como
hora local DEL SISTEMA. Sintoma: con ``TZ=America/Argentina/Buenos_Aires`` en
la imagen, todas las ventanas del panel ("hoy", "esta semana", "la semana
pasada", "nuevos clientes 30 d") se corren tres horas y dejan de coincidir con
``/reports``, que si manda aware. Hoy no pasa solo porque el compose no define
``TZ``: la correccion no puede depender de una omision.

En SQLite el naive y el aware dan lo mismo, asi que ningun test de integracion
puede ver la diferencia: estos tests miran el parametro que se manda a la base
y el archivo que lo produce. El caso de punta a punta vive en
``tests/postgres/test_pg_panel_dia_local.py``.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import BindParameter

import modules.dashboard.repository as repositorio
from modules.dashboard.repository import _starts_between

DESDE = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
HASTA = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)


def test_los_limites_del_rango_viajan_aware() -> None:
    parametros = []
    for predicado in _starts_between(DESDE, HASTA):
        derecha = predicado.right
        assert isinstance(derecha, BindParameter)
        parametros.append(derecha.value)
    assert parametros == [DESDE, HASTA]
    for valor in parametros:
        assert valor.tzinfo is not None, "un naive lo interpreta la TZ del host"


def test_ninguna_consulta_del_panel_descarta_la_zona() -> None:
    """Las otras dos ventanas (nuevos clientes, en ``day_counters``, y
    proximos turnos) tambien.

    Se mira el archivo porque el defecto es una llamada puntual repetida: si
    vuelve en una consulta nueva, el sintoma no lo ve ningun test en SQLite.
    """
    fuente = Path(repositorio.__file__).read_text(encoding="utf-8")
    assert "replace(tzinfo=None)" not in fuente


@pytest.mark.parametrize("nombre", ["day_counters", "upcoming"])
def test_las_ventanas_sueltas_siguen_existiendo(nombre: str) -> None:
    """Guarda del test anterior: si el metodo se renombra, hay que revisarlo."""
    assert hasattr(repositorio.DashboardRepository, nombre)
