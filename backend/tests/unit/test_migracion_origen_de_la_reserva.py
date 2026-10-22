"""La migracion ``733220bbf66e`` marca ``booked_via = 'portal'`` en lo historico.

2026-10-22, paquete antiabuso (S5). ``appointments.booked_via`` nace con el
default ``'panel'`` (``c7cd51eba96c``) y el backfill marca ``'portal'`` donde
hay ``terms_accepted_at``: solo el portal lo escribe (la reserva publica y la
oferta de la lista de espera aceptada por el cliente); el panel deja NULL
porque el personal no es el cliente dando su consentimiento.

Por lotes con clave por id, como ``b5d7f9a1c3e6``. Se corre contra SQLite con
la conexion cruda, como ``test_migracion_minimizar_raw_payload.py``.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Connection, create_engine, text

MIGRACION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "733220bbf66e_appointments_booked_via_backfill.py"
)


def _migracion() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migracion_s5", MIGRACION)
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
                "create table appointments (id varchar primary key, "
                "terms_accepted_at timestamp, "
                "booked_via varchar(20) not null default 'panel')"
            )
        )
        yield conn
    motor.dispose()


def _cargar(conn: Connection, filas: dict[str, str | None]) -> None:
    for id_, aceptado in filas.items():
        conn.execute(
            text("insert into appointments (id, terms_accepted_at) values (:i, :t)"),
            {"i": id_, "t": aceptado},
        )


def _origenes(conn: Connection) -> dict[str, str]:
    filas = conn.execute(text("select id, booked_via from appointments")).all()
    return {str(id_): str(origen) for id_, origen in filas}


def test_marca_portal_solo_donde_hay_terminos_aceptados(conexion: Connection) -> None:
    _cargar(
        conexion,
        {
            "a1": "2026-10-01 10:00:00",
            "a2": None,
            "a3": "2026-10-02 11:00:00",
            "a4": None,
            "a5": "2026-10-03 12:00:00",
        },
    )

    # Lote de 2: cinco filas obligan a tres lecturas y la clave por id no
    # saltea ni repite ninguna.
    cambiadas = _migracion().marcar_portal(conexion, lote=2)

    assert cambiadas == 3
    assert _origenes(conexion) == {
        "a1": "portal",
        "a2": "panel",
        "a3": "portal",
        "a4": "panel",
        "a5": "portal",
    }


def test_una_segunda_corrida_no_cambia_nada(conexion: Connection) -> None:
    _cargar(conexion, {"b1": "2026-10-01 10:00:00", "b2": None})
    modulo = _migracion()
    assert modulo.marcar_portal(conexion, lote=1) == 1

    assert modulo.marcar_portal(conexion, lote=1) == 0
    assert _origenes(conexion) == {"b1": "portal", "b2": "panel"}


def test_sin_filas_no_hace_nada(conexion: Connection) -> None:
    assert _migracion().marcar_portal(conexion) == 0
