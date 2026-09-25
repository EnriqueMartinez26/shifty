"""La migracion ``c5e7a9b1d3f4`` agrega ``audit_logs.store_id`` con backfill real.

B3-11, 2026-09-18. Se corre el ``upgrade``/``downgrade`` de la migracion contra
SQLite con ``Operations`` de Alembic (la cadena completa no corre en SQLite por
sus pasos de RLS). La version contra Postgres, con el rol dueno y alembic en
proceso aparte, esta en ``tests/postgres/test_pg_audit_logs_store_id.py``.

Fija el backfill por tipo de recurso, que lo global (planes, cupones) y lo no
derivable (recurso que ya no existe) quedan en NULL sin borrar filas, y que el
``downgrade`` deja la tabla como estaba.
"""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, create_engine, text

MIGRACION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "c5e7a9b1d3f4_audit_logs_store_id.py"
)


def _migracion() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migracion_b3_11", MIGRACION)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def conexion() -> Iterator[Connection]:
    motor = create_engine("sqlite://")
    with motor.begin() as conn:
        conn.execute(
            text("create table stores (id varchar primary key, public_id varchar)")
        )
        for tabla in (
            "users",
            "store_subscriptions",
            "coupon_redemptions",
            "appointments",
            "appointment_blocks",
        ):
            conn.execute(
                text(f"create table {tabla} (id varchar primary key, store_id varchar)")
            )
        conn.execute(
            text(
                "create table audit_logs (id integer primary key, "
                "resource_type varchar, resource_id varchar, context varchar)"
            )
        )
        conn.execute(text("insert into stores values ('tienda-1', 'pid-tienda-1')"))
        for tabla, fila in (
            ("users", "user-1"),
            ("store_subscriptions", "sub-1"),
            ("coupon_redemptions", "canje-1"),
            ("appointments", "turno-1"),
            ("appointment_blocks", "bloqueo-1"),
        ):
            conn.execute(
                text(f"insert into {tabla} values (:id, 'tienda-1')"), {"id": fila}
            )
        yield conn
    motor.dispose()


FILAS = (
    ("Store", "pid-tienda-1", "tienda-1"),
    ("User", "user-1", "tienda-1"),
    ("StoreSubscription", "sub-1", "tienda-1"),
    ("CouponRedemption", "canje-1", "tienda-1"),
    ("Appointment", "turno-1", "tienda-1"),
    ("AppointmentBlock", "bloqueo-1", "tienda-1"),
    ("Plan", "plan-1", None),
    ("SaaSCoupon", "cupon-1", None),
    ("User", "usuario-que-ya-no-existe", None),
    ("TipoDesconocido", "x", None),
)


def _correr(conn: Connection, paso: str) -> None:
    contexto = MigrationContext.configure(conn)
    with Operations.context(contexto):
        getattr(_migracion(), paso)()


def _columnas(conn: Connection) -> list[str]:
    return [fila[1] for fila in conn.execute(text("pragma table_info(audit_logs)"))]


def test_el_backfill_deriva_la_tienda_del_recurso_auditado(
    conexion: Connection,
) -> None:
    for tipo, recurso, _ in FILAS:
        conexion.execute(
            text(
                "insert into audit_logs (resource_type, resource_id, context) "
                "values (:t, :r, 'superadmin')"
            ),
            {"t": tipo, "r": recurso},
        )

    _correr(conexion, "upgrade")

    obtenido = {
        (tipo, recurso): store_id
        for tipo, recurso, store_id in conexion.execute(
            text("select resource_type, resource_id, store_id from audit_logs")
        )
    }
    assert obtenido == {(tipo, recurso): esperado for tipo, recurso, esperado in FILAS}
    total = conexion.execute(text("select count(*) from audit_logs")).scalar_one()
    assert total == len(FILAS), "el backfill no puede borrar filas"


def test_downgrade_y_upgrade_de_nuevo(conexion: Connection) -> None:
    conexion.execute(
        text(
            "insert into audit_logs (resource_type, resource_id, context) "
            "values ('Store', 'pid-tienda-1', 'superadmin')"
        )
    )
    _correr(conexion, "upgrade")
    assert "store_id" in _columnas(conexion)

    _correr(conexion, "downgrade")
    assert "store_id" not in _columnas(conexion)
    indices = [
        fila[1] for fila in conexion.execute(text("pragma index_list(audit_logs)"))
    ]
    assert "ix_audit_logs_store_id" not in indices

    _correr(conexion, "upgrade")
    assert (
        conexion.execute(text("select store_id from audit_logs")).scalar_one()
        == "tienda-1"
    )
