"""La migracion ``c7e9a1b3d5f7`` borra el texto de las notas de ``audit_logs``.

2026-09-25, L3-02. Las filas escritas antes del cambio de
``update_staff_notes`` tienen el texto completo de ``notes_staff`` en
``payload_before``/``payload_after``. La migracion las deja con la misma
forma que escribe el codigo nuevo (marca y largo), por lotes, sin tocar
ninguna otra fila de auditoria. Contra SQLite con ``Operations`` de Alembic.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, create_engine, text

MIGRACION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "c7e9a1b3d5f7_auditoria_de_notas_sin_texto.py"
)


def _migracion() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migracion_l3_02", MIGRACION)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def conexion() -> Iterator[Connection]:
    motor = create_engine("sqlite://")
    with motor.begin() as conn:
        conn.execute(
            text(
                "create table audit_logs (id integer primary key, "
                "resource_type varchar, action varchar, "
                "payload_before json, payload_after json)"
            )
        )
        yield conn
    motor.dispose()


# (resource_type, action, before, after)
FILAS: list[tuple[str, str, Any, Any]] = [
    ("Appointment", "update", {"notes_staff": None}, {"notes_staff": "ansiedad"}),
    ("Appointment", "update", {"notes_staff": "ansiedad"}, {"notes_staff": "ok"}),
    ("Appointment", "status_change", {"status": "pending"}, {"status": "confirmed"}),
    ("User", "update", {"first_name": "Ana"}, {"first_name": "Ana Maria"}),
    ("Appointment", "update", None, None),
]

ESPERADO: list[tuple[Any, Any]] = [
    (
        {"notes_staff_changed": True, "notes_staff_length": 0},
        {"notes_staff_changed": True, "notes_staff_length": 8},
    ),
    (
        {"notes_staff_changed": True, "notes_staff_length": 8},
        {"notes_staff_changed": True, "notes_staff_length": 2},
    ),
    ({"status": "pending"}, {"status": "confirmed"}),
    ({"first_name": "Ana"}, {"first_name": "Ana Maria"}),
    (None, None),
]


def _sembrar(conn: Connection) -> None:
    for tipo, accion, antes, despues in FILAS:
        conn.execute(
            text(
                "insert into audit_logs "
                "(resource_type, action, payload_before, payload_after) "
                "values (:t, :a, :b, :d)"
            ),
            {
                "t": tipo,
                "a": accion,
                "b": None if antes is None else json.dumps(antes),
                "d": None if despues is None else json.dumps(despues),
            },
        )


def _leer(conn: Connection) -> list[tuple[Any, Any]]:
    def _cargar(valor: Any) -> Any:
        return None if valor is None else json.loads(valor)

    return [
        (_cargar(antes), _cargar(despues))
        for antes, despues in conn.execute(
            text("select payload_before, payload_after from audit_logs order by id")
        )
    ]


def test_upgrade_deja_la_marca_y_el_largo_sin_el_texto(conexion: Connection) -> None:
    _sembrar(conexion)
    contexto = MigrationContext.configure(conexion)
    with Operations.context(contexto):
        _migracion().upgrade()
    assert _leer(conexion) == ESPERADO
    total = conexion.execute(text("select count(*) from audit_logs")).scalar_one()
    assert total == len(FILAS), "el recorte no puede borrar filas"


def test_por_lotes_e_idempotente(conexion: Connection) -> None:
    _sembrar(conexion)
    assert _migracion().recortar_notas(conexion, lote=1) == 2
    assert _leer(conexion) == ESPERADO
    assert _migracion().recortar_notas(conexion, lote=1) == 0


def test_downgrade_no_falla(conexion: Connection) -> None:
    _sembrar(conexion)
    contexto = MigrationContext.configure(conexion)
    with Operations.context(contexto):
        _migracion().upgrade()
        _migracion().downgrade()
    assert _leer(conexion) == ESPERADO
