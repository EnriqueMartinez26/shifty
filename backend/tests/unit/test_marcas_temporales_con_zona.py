"""Ninguna marca temporal del esquema es naive (regla 24).

2026-09-18, hallazgo B5-13: ``audit_logs.created_at`` era ``DateTime`` sin
zona con ``server_default now()``, la unica del backend asi. La app nunca fija
``SET TIME ZONE``: el valor quedaba en la hora de pared de la sesion de
Postgres y ``AuditLogResponse`` le entregaba al front un instante sin zona que
no podia convertir. El resto del esquema (``appointments.starts_at`` y demas)
ya era ``timestamptz``.

SQLite no distingue: devuelve naive con o sin ``timezone=True``. Por eso la
guarda es sobre el modelo (que es lo que usa ``create_all`` en la suite y lo
que la migracion ``a1c3e5b7d9f2`` alinea en Postgres) y sobre el DDL que
SQLAlchemy emite para Postgres. El instante real tras la migracion lo prueba
``tests/postgres/test_pg_audit_logs_timestamptz.py``.
"""

from typing import cast

from sqlalchemy import DateTime, Table, create_engine
from sqlalchemy.schema import CreateTable

from core.model_registry import load_all_models
from core.models import Base
from modules.audit.model import AuditLog


def test_ninguna_columna_datetime_del_esquema_es_naive() -> None:
    load_all_models()
    naive = [
        f"{tabla.name}.{columna.name}"
        for tabla in Base.metadata.sorted_tables
        for columna in tabla.columns
        if isinstance(columna.type, DateTime) and not columna.type.timezone
    ]
    assert naive == []


def test_audit_logs_created_at_es_timestamptz_en_postgres() -> None:
    tabla = cast(Table, AuditLog.__table__)
    ddl = str(
        CreateTable(tabla).compile(
            dialect=create_engine("postgresql+psycopg2://").dialect
        )
    )
    linea = next(line for line in ddl.splitlines() if "created_at" in line)
    assert "TIMESTAMP WITH TIME ZONE" in linea, linea
    assert "DEFAULT now()" in linea, linea
