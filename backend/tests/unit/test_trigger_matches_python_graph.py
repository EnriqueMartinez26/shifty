"""Equivalencia entre el grafo de Python y el trigger de PostgreSQL.

El grafo de transiciones existe en dos representaciones: el diccionario
``ALLOWED_STATUS_TRANSITIONS`` y la funcion PL/pgSQL de la migracion. Eliminamos
la duplicacion dentro de Python pero la reintrodujimos entre lenguajes.

Este test parsea el SQL de la migracion y lo contrasta contra el diccionario,
asi que un cambio en uno solo de los dos lados rompe CI en vez de quedar como
una divergencia silenciosa. No necesita PostgreSQL: es analisis estatico.
"""

import importlib.util
from pathlib import Path
import re

from infrastructure.persistence.models.appointment import ALLOWED_STATUS_TRANSITIONS

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "b2c3d4e5f6a7_statechart_hardening.py"
)


def _load_trigger_sql() -> str:
    spec = importlib.util.spec_from_file_location("statechart_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module._TRANSITION_GUARD)


def _transitions_declared_in_sql() -> dict[str, set[str]]:
    """Extrae los pares (origen, destinos) de las clausulas OLD.status = '...'."""
    sql = _load_trigger_sql()
    pattern = re.compile(
        r"OLD\.status\s*=\s*'(?P<origen>\w+)'\s*AND\s*NEW\.status\s*IN\s*\((?P<destinos>[^)]*)\)",
        re.IGNORECASE | re.DOTALL,
    )
    parsed: dict[str, set[str]] = {}
    for match in pattern.finditer(sql):
        destinos = set(re.findall(r"'(\w+)'", match.group("destinos")))
        parsed[match.group("origen")] = destinos
    return parsed


def test_el_trigger_declara_las_mismas_transiciones_que_python() -> None:
    sql_graph = _transitions_declared_in_sql()
    python_graph = {
        origen: destinos
        for origen, destinos in ALLOWED_STATUS_TRANSITIONS.items()
        if destinos  # los terminales no aparecen en el SQL: no tienen clausula
    }

    assert sql_graph, "no se pudo parsear ninguna transicion del trigger"
    assert sql_graph == python_graph, (
        "El trigger de PostgreSQL y ALLOWED_STATUS_TRANSITIONS divergieron.\n"
        f"  SQL:    {sql_graph}\n"
        f"  Python: {python_graph}"
    )


def test_los_estados_terminales_no_tienen_clausula_en_el_trigger() -> None:
    """Un terminal sin clausula cae en el RAISE: toda salida queda bloqueada."""
    sql_graph = _transitions_declared_in_sql()
    terminales = {
        origen
        for origen, destinos in ALLOWED_STATUS_TRANSITIONS.items()
        if not destinos
    }
    assert terminales
    for terminal in terminales:
        assert terminal not in sql_graph, (
            f"'{terminal}' es terminal en Python pero el trigger le permite salidas"
        )
