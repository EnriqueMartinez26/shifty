"""La migracion ``b5d7f9a1c3e6`` recorta el ``raw_payload`` historico de pagos.

2026-09-25, L3-01. El codigo nuevo guarda solo la lista blanca
(``modules/payments/minimization.py``), pero las filas ya escritas conservan
email, identificacion y tarjeta del pagador. La migracion las recorta por
lotes (clave por id) y no toca los payloads internos (motivo de vencimiento,
nota de la confirmacion manual, datos del reembolso), que no vienen de MP.

Se corre contra SQLite con ``Operations`` de Alembic, como
``test_migracion_audit_logs_store_id.py``.
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
    / "b5d7f9a1c3e6_minimizar_raw_payload_de_pagos.py"
)


def _migracion() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migracion_l3_01", MIGRACION)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def conexion() -> Iterator[Connection]:
    motor = create_engine("sqlite://")
    with motor.begin() as conn:
        conn.execute(
            text("create table payments (id varchar primary key, raw_payload json)")
        )
        yield conn
    motor.dispose()


PAGADOR = {"email": "pagador@example.com", "identification": {"number": "30123456"}}

FILAS: dict[str, Any] = {
    "p1-preferencia": {
        "id": "pref-1",
        "init_point": "https://mp/1",
        "payer": PAGADOR,
        "items": [{"title": "Consulta"}],
    },
    "p2-conciliacion": {
        "status": "approved",
        "data": {
            "id": "mp-1",
            "status": "approved",
            "transaction_amount": 10.0,
            "payer": PAGADOR,
            "card": {"last_four_digits": "3704"},
        },
    },
    "p3-vencido": {"reason": "manual_store_release", "released_by": "u1"},
    "p4-reembolso": {"reason": "pedido", "manual": True, "refunded_amount": "10"},
    "p5-webhook-limpio": {"status": "approved", "data": {"id": "mp-2"}},
    "p6-nulo": None,
}

ESPERADO: dict[str, Any] = {
    "p1-preferencia": {"id": "pref-1", "init_point": "https://mp/1"},
    "p2-conciliacion": {
        "status": "approved",
        "data": {"id": "mp-1", "status": "approved", "transaction_amount": 10.0},
    },
    "p3-vencido": FILAS["p3-vencido"],
    "p4-reembolso": FILAS["p4-reembolso"],
    "p5-webhook-limpio": FILAS["p5-webhook-limpio"],
    "p6-nulo": None,
}


def _sembrar(conn: Connection) -> None:
    for id_, payload in FILAS.items():
        conn.execute(
            text("insert into payments (id, raw_payload) values (:i, :p)"),
            {"i": id_, "p": None if payload is None else json.dumps(payload)},
        )


def _leer(conn: Connection) -> dict[str, Any]:
    return {
        id_: None if valor is None else json.loads(valor)
        for id_, valor in conn.execute(text("select id, raw_payload from payments"))
    }


def test_upgrade_recorta_lo_que_vino_de_mp_y_deja_lo_interno(
    conexion: Connection,
) -> None:
    _sembrar(conexion)
    contexto = MigrationContext.configure(conexion)
    with Operations.context(contexto):
        _migracion().upgrade()
    assert _leer(conexion) == ESPERADO


def test_por_lotes_cuenta_solo_las_filas_que_cambio(conexion: Connection) -> None:
    _sembrar(conexion)
    # Lote de 2 sobre 6 filas: fuerza tres vueltas del recorrido por clave.
    assert _migracion().minimizar(conexion, lote=2) == 2
    assert _leer(conexion) == ESPERADO
    # Idempotente: una segunda corrida no encuentra nada que recortar.
    assert _migracion().minimizar(conexion, lote=2) == 0


def test_downgrade_no_falla_y_no_restaura_datos(conexion: Connection) -> None:
    _sembrar(conexion)
    contexto = MigrationContext.configure(conexion)
    with Operations.context(contexto):
        _migracion().upgrade()
        _migracion().downgrade()
    assert _leer(conexion) == ESPERADO
