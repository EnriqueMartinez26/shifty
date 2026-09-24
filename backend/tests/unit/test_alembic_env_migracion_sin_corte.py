"""F0-06 (plan de rendimiento): una migracion no puede frenar la app entera.

Sintoma que previene: una migracion que pide un lock fuerte (ALTER TABLE,
CREATE INDEX sin CONCURRENTLY) sobre una tabla con una transaccion larga
abierta se queda ESPERANDO el lock, y detras de ella se encolan todas las
consultas de la app sobre esa tabla: el deploy tumba la API sin que la
migracion haga nada. Con `lock_timeout` la migracion aborta a los 3 s y el
deploy falla a la vista, con el codigo viejo sirviendo.

Y con `transaction_per_migration` cada revision commitea sola: una cadena de
diez migraciones ya no retiene los locks de la primera hasta que termina la
ultima, y un fallo en la sexta deja aplicadas (y registradas) las cinco
anteriores en vez de revertir todo.

`env.py` no es importable como modulo normal (ver
test_alembic_env_no_filtra_credenciales.py): se ejecuta con `alembic.context`
reemplazado por un doble que registra lo que `env.py` le pide. La prueba de
comportamiento contra Postgres real esta en tests/postgres/test_pg_migraciones.py.
"""

import contextlib
import importlib.util
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import alembic
import pytest
import sqlalchemy

from core.config import settings

ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"
URL_VALIDA = (
    "postgresql+asyncpg://shifty_owner:Otr0S3cr3t@db:5432/shifty_db?ssl=disable"
)


class _Registro:
    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.configure: dict[str, Any] = {}


class _Conexion:
    def __init__(self, registro: _Registro) -> None:
        self._registro = registro

    def __enter__(self) -> "_Conexion":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def exec_driver_sql(self, sql: str, *_: object) -> None:
        self._registro.eventos.append(f"sql:{sql}")

    def commit(self) -> None:
        self._registro.eventos.append("commit")


class _Engine:
    def __init__(self, registro: _Registro) -> None:
        self._registro = registro

    def connect(self) -> _Conexion:
        return _Conexion(self._registro)


def _contexto(registro: _Registro, offline: bool) -> type:
    class _Contexto:
        config = types.SimpleNamespace(config_file_name=None)

        @staticmethod
        def is_offline_mode() -> bool:
            return offline

        @staticmethod
        def configure(**kwargs: Any) -> None:
            registro.eventos.append("configure")
            registro.configure = kwargs

        @staticmethod
        def begin_transaction() -> contextlib.AbstractContextManager[None]:
            return contextlib.nullcontext()

        @staticmethod
        def run_migrations() -> None:
            registro.eventos.append("run_migrations")

    return _Contexto


@pytest.fixture
def ejecutar_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def _ejecutar(*, offline: bool) -> _Registro:
        registro = _Registro()
        monkeypatch.setattr(alembic, "context", _contexto(registro, offline))
        # env.py hace `from sqlalchemy import create_engine` al ejecutarse.
        monkeypatch.setattr(
            sqlalchemy, "create_engine", lambda *_a, **_k: _Engine(registro)
        )
        monkeypatch.setattr(settings, "MIGRATION_DATABASE_URL", URL_VALIDA)
        spec = importlib.util.spec_from_file_location("alembic_env_sin_corte", ENV_PY)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
        return registro

    yield _ejecutar


def test_online_fija_lock_timeout_antes_de_migrar(ejecutar_env: Any) -> None:
    registro = ejecutar_env(offline=False)
    sentencias = [e for e in registro.eventos if e.startswith("sql:")]
    assert "sql:SET lock_timeout = '3s'" in sentencias, registro.eventos
    # El rol dueno no hereda los timeouts del rol de la app; un statement
    # timeout heredado de la sesion cortaria un backfill legitimo a la mitad.
    assert "sql:SET statement_timeout = 0" in sentencias, registro.eventos


def test_online_commitea_los_set_antes_de_configurar(ejecutar_env: Any) -> None:
    """Los SET abren una transaccion (autobegin de SQLAlchemy 2). Si sigue
    abierta al configurar, Alembic la toma como externa: no abre una por
    migracion y nada se commitea."""
    registro = ejecutar_env(offline=False)
    eventos = registro.eventos
    assert "commit" in eventos and "configure" in eventos, eventos
    ultimo_set = max(i for i, e in enumerate(eventos) if e.startswith("sql:"))
    assert ultimo_set < eventos.index("commit") < eventos.index("configure"), eventos
    assert eventos[-1] == "run_migrations", eventos


@pytest.mark.parametrize("offline", [False, True])
def test_cada_migracion_va_en_su_transaccion(ejecutar_env: Any, offline: bool) -> None:
    registro = ejecutar_env(offline=offline)
    assert registro.configure.get("transaction_per_migration") is True, (
        f"offline={offline}: {registro.configure!r}"
    )
