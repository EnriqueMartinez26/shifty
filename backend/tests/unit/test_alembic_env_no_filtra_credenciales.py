"""2026-09-16 · C-01: `alembic/env.py` metia la URL completa en el error de parseo.

Sintoma: con `MIGRATION_DATABASE_URL=postgres://shifty_user:S3cr3t@/` (esquema
`postgres` en vez de `postgresql`), `alembic upgrade head` moria con
`ValueError: No se pudo parsear DATABASE_URL: postgres://shifty_user:S3cr3t@/`.
Esa URL es la del rol DUENO de la base, y el traceback queda en
`docker compose logs`, en el log de CI y en el artefacto del job fallido.

`env.py` no es importable como modulo normal: al final ejecuta
`context.is_offline_mode()` sobre el proxy de Alembic, que fuera de una
corrida real levanta NameError. Aca se reemplaza `alembic.context` por un
stub en modo offline, se fija `settings.MIGRATION_DATABASE_URL` y se ejecuta
el archivo tal cual lo ejecutaria Alembic.
"""

import contextlib
import importlib.util
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import alembic
import pytest
from sqlalchemy.engine import make_url

from core.config import settings

ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"

URL_HOSTIL = "postgres://shifty_user:S3cr3t@/"
URL_VALIDA = "postgresql+asyncpg://shifty_owner:Otr0S3cr3t@db:5432/shifty_db"

# Password con los cinco caracteres que rompen una URL si no se re-escapan al
# rearmarla: `@`, `/`, `:`, `?` y `#`. Se declara ya escapada, como vendria del
# entorno (AUD2-B7-10).
PASSWORD_CON_SIMBOLOS = "p@ss/w:rd?#"
URL_CON_PASSWORD_HOSTIL = "postgresql+asyncpg://shifty_owner:p%40ss%2Fw%3Ard%3F%23@db:5432/shifty_db?ssl=require"


class _ContextoOffline:
    """Lo minimo de `alembic.context` que `env.py` toca en modo offline."""

    config = types.SimpleNamespace(config_file_name=None)

    @staticmethod
    def is_offline_mode() -> bool:
        return True

    # `run_migrations_offline` arma la URL a mano y se la pasa a `configure`:
    # es el unico lugar donde se puede mirar (AUD2-B7-10).
    url_configurada: str | None = None

    @classmethod
    def configure(cls, **kwargs: Any) -> None:
        url = kwargs.get("url")
        cls.url_configurada = None if url is None else str(url)

    @staticmethod
    def begin_transaction() -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()

    @staticmethod
    def run_migrations() -> None:
        return None


@pytest.fixture
def cargar_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(alembic, "context", _ContextoOffline)

    def _cargar(migration_url: str) -> types.ModuleType:
        monkeypatch.setattr(settings, "MIGRATION_DATABASE_URL", migration_url)
        spec = importlib.util.spec_from_file_location("alembic_env_bajo_test", ENV_PY)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    yield _cargar


def test_parse_db_url_no_incluye_usuario_ni_password_en_el_error(
    cargar_env: Any,
) -> None:
    env = cargar_env(URL_VALIDA)

    with pytest.raises(ValueError) as excinfo:
        env.parse_db_url(URL_HOSTIL)

    mensaje = str(excinfo.value)
    assert "S3cr3t" not in mensaje
    assert "shifty_user" not in mensaje
    # Lo no sensible sigue ahi para diagnosticar: el esquema que no matcheo,
    # con la misma redaccion que run_migrations.py (helper unico, S-01).
    assert "postgres://[redacted]@" in mensaje


def test_env_py_con_migration_url_invalida_no_filtra_la_password(
    cargar_env: Any,
) -> None:
    """El camino real: `settings.MIGRATION_DATABASE_URL` invalida al ejecutar env.py."""
    with pytest.raises(ValueError) as excinfo:
        cargar_env(URL_HOSTIL)

    mensaje = str(excinfo.value)
    assert "S3cr3t" not in mensaje
    assert "shifty_user" not in mensaje


def test_parse_db_url_sigue_extrayendo_los_componentes(cargar_env: Any) -> None:
    """Contrato intacto: el parseo del camino feliz no cambia."""
    env = cargar_env(URL_VALIDA)

    params = env.parse_db_url(
        "postgresql+asyncpg://shifty_owner:p%40ss@db:5433/shifty_db?sslmode=require"
    )

    assert params == {
        "user": "shifty_owner",
        "password": "p@ss",
        "host": "db",
        "port": 5433,
        "dbname": "shifty_db",
        "sslmode": "require",
    }


def test_la_url_del_modo_offline_sobrevive_a_una_password_con_simbolos(
    cargar_env: Any,
) -> None:
    """AUD2-B7-10 (2026-09-20): `run_migrations_offline` rearmaba la URL cruda.

    Sintoma: `parse_db_url` devuelve usuario y password ya des-escapados
    (`unquote`), y el modo offline los volvia a meter en un f-string sin
    re-escaparlos. Con `p@ss/w:rd?#`, la URL resultante la leia `make_url` como
    otro usuario, otro host y otra base; el error de SQLAlchemy que sigue puede
    llevar la URL cruda (regla 20). El modo online no tiene el problema porque
    pasa los componentes por `connect_args`.
    """
    _ContextoOffline.url_configurada = None

    cargar_env(URL_CON_PASSWORD_HOSTIL)

    assert _ContextoOffline.url_configurada is not None
    url = make_url(_ContextoOffline.url_configurada)
    assert url.username == "shifty_owner"
    assert url.password == PASSWORD_CON_SIMBOLOS
    assert url.host == "db"
    assert url.port == 5432
    assert url.database == "shifty_db"


def test_la_url_del_modo_offline_sobrevive_a_un_usuario_con_simbolos(
    cargar_env: Any,
) -> None:
    """El usuario se rearma por el mismo camino que la password."""
    _ContextoOffline.url_configurada = None

    cargar_env("postgresql+asyncpg://shifty%40owner:simple@db:5432/shifty_db")

    assert _ContextoOffline.url_configurada is not None
    url = make_url(_ContextoOffline.url_configurada)
    assert url.username == "shifty@owner"
    assert url.password == "simple"
    assert url.database == "shifty_db"
