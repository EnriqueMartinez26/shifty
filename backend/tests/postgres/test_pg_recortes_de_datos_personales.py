"""Los recortes de datos de ``b5d7f9a1c3e6`` y ``c7e9a1b3d5f7`` en Postgres real.

2026-09-25, L3-01 y L3-02. Los tests unitarios corren esas migraciones contra
SQLite, donde el JSON vuelve como texto. En Postgres (psycopg2, columna
``json``) vuelve decodificado y el UPDATE tiene que serializarlo: esto lo
prueba sobre tablas con la misma forma en un esquema aparte (sin tocar el
esquema migrado ni sus FKs), en ``autocommit`` como corre la migracion.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg2

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.postgres.conftest import HABILITADO, OWNER_URL, _sync_dsn

pytestmark = pytest.mark.postgres

VERSIONES = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _migracion(archivo: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(archivo, VERSIONES / archivo)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def conexion() -> Iterator[Connection]:
    if not HABILITADO:
        pytest.skip("Postgres real no configurado")
    assert OWNER_URL
    motor = create_engine(
        "postgresql+psycopg2://",
        creator=lambda: _psycopg2(),
        isolation_level="AUTOCOMMIT",
    )
    with motor.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS recortes CASCADE"))
        conn.execute(text("CREATE SCHEMA recortes"))
        conn.execute(text("SET search_path TO recortes"))
        conn.execute(
            text("CREATE TABLE payments (id varchar PRIMARY KEY, raw_payload json)")
        )
        conn.execute(
            text(
                "CREATE TABLE audit_logs (id serial PRIMARY KEY, resource_type "
                "varchar, action varchar, payload_before json, payload_after json)"
            )
        )
        try:
            yield conn
        finally:
            conn.execute(text("SET search_path TO public"))
            conn.execute(text("DROP SCHEMA recortes CASCADE"))
    motor.dispose()


def _psycopg2() -> Any:
    assert OWNER_URL
    return psycopg2.connect(_sync_dsn(OWNER_URL))


def test_el_recorte_de_pagos_serializa_bien_en_postgres(conexion: Connection) -> None:
    conexion.execute(
        text("INSERT INTO payments VALUES ('p1', CAST(:p AS json)), ('p2', NULL)"),
        {
            "p": json.dumps(
                {
                    "status": "approved",
                    "data": {
                        "id": "mp-1",
                        "status": "approved",
                        "payer": {"email": "x@example.com"},
                    },
                }
            )
        },
    )

    assert (
        _migracion("b5d7f9a1c3e6_minimizar_raw_payload_de_pagos.py").minimizar(
            conexion, lote=1
        )
        == 1
    )

    fila = conexion.execute(
        text("SELECT raw_payload::text FROM payments WHERE id = 'p1'")
    ).scalar_one()
    assert json.loads(fila) == {
        "status": "approved",
        "data": {"id": "mp-1", "status": "approved"},
    }
    assert (
        conexion.execute(
            text("SELECT raw_payload IS NULL FROM payments WHERE id = 'p2'")
        ).scalar_one()
        is True
    )


def test_el_recorte_de_notas_serializa_bien_en_postgres(conexion: Connection) -> None:
    conexion.execute(
        text(
            "INSERT INTO audit_logs (resource_type, action, payload_before, "
            "payload_after) VALUES ('Appointment', 'update', "
            "CAST(:b AS json), CAST(:d AS json))"
        ),
        {
            "b": json.dumps({"notes_staff": None}),
            "d": json.dumps({"notes_staff": "nota clinica"}),
        },
    )

    modulo = _migracion("c7e9a1b3d5f7_auditoria_de_notas_sin_texto.py")
    assert modulo.recortar_notas(conexion) == 1

    antes, despues = conexion.execute(
        text("SELECT payload_before::text, payload_after::text FROM audit_logs")
    ).one()
    assert json.loads(antes) == {"notes_staff_changed": True, "notes_staff_length": 0}
    assert json.loads(despues) == {
        "notes_staff_changed": True,
        "notes_staff_length": 12,
    }
