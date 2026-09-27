"""Una sola lectura de la URL de base para migrar, con TLS por defecto (B7-11, S-10).

2026-09-19. Sintomas:
- `parse_db_url` estaba duplicada (`run_migrations.py` y `alembic/env.py`) con
  el `sslmode` por defecto distinto: `require` en el script, `disable` en
  Alembic. El mismo entorno daba dos respuestas.
- Las dos copias leian solo `sslmode`, pero las URLs del repo son de asyncpg,
  que usa `ssl`: la de produccion de ejemplo (`?ssl=require`) se ignoraba y
  Alembic migraba produccion SIN TLS (`disable`).
- `sslmode=` no sirve en esas URLs: SQLAlchemy+asyncpg lo pasa como kwarg a
  `asyncpg.connect`, que no lo acepta; la API no arrancaria.

Decision (OK global del usuario; opcion B del coordinador): helper unico
`core.config.parse_db_url` que lee `ssl`, acepta `sslmode` por compatibilidad
y usa `require` cuando falta. El compose declara `?ssl=${POSTGRES_SSL:-disable}`
una sola vez en `x-app-environment`; CI y `.env.example` traen `?ssl=disable`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

import core.config

BACKEND = Path(__file__).resolve().parents[2]
RAIZ = BACKEND.parent
LOCAL = "postgresql+asyncpg://shifty_user:shifty_password@127.0.0.1:5432/shifty_test"


def _parse(url: str, **kwargs: Any) -> dict[str, Any]:
    # Por el modulo: si el helper no existe, falla la asercion, no la coleccion.
    resultado: dict[str, Any] = core.config.parse_db_url(url, **kwargs)
    return resultado


@pytest.mark.parametrize(
    ("sufijo", "esperado"),
    [
        ("", "require"),
        ("?ssl=disable", "disable"),
        ("?ssl=require", "require"),
        ("?ssl=verify-full", "verify-full"),
        ("?sslmode=disable", "disable"),
        ("?sslmode=require&ssl=require", "require"),
    ],
    ids=[
        "sin-nada",
        "ssl-disable",
        "ssl-require",
        "ssl-verify-full",
        "sslmode",
        "ambos-iguales",
    ],
)
def test_el_helper_resuelve_el_modo_tls(sufijo: str, esperado: str) -> None:
    assert _parse(LOCAL + sufijo)["sslmode"] == esperado


def test_el_helper_extrae_los_componentes() -> None:
    assert _parse(
        "postgresql+asyncpg://shifty_owner:p%40ss@db:5433/shifty_db?ssl=disable"
    ) == {
        "user": "shifty_owner",
        "password": "p@ss",
        "host": "db",
        "port": 5433,
        "dbname": "shifty_db",
        "sslmode": "disable",
    }


def test_la_url_de_produccion_de_ejemplo_migra_con_tls() -> None:
    """El bug: `?ssl=require` se ignoraba y Alembic migraba produccion en `disable`."""
    ejemplo = (BACKEND / ".env.production.example").read_text(encoding="utf-8")
    url = re.search(r"^DATABASE_URL=(\S+)$", ejemplo, re.MULTILINE)
    assert url is not None

    assert _parse(url.group(1))["sslmode"] == "require"


@pytest.mark.parametrize(
    "sufijo",
    ["?ssl=cualquiera", "?ssl=require&sslmode=disable"],
    ids=["invalido", "contradictorio"],
)
def test_un_modo_invalido_o_contradictorio_no_se_adivina(sufijo: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        _parse(LOCAL + sufijo, label="MIGRATION_DATABASE_URL")

    mensaje = str(excinfo.value)
    assert "MIGRATION_DATABASE_URL" in mensaje
    assert "shifty_password" not in mensaje and "shifty_user" not in mensaje


def test_una_url_que_no_parsea_no_filtra_credenciales() -> None:
    with pytest.raises(ValueError) as excinfo:
        _parse("postgres://shifty_user:S3cr3t@/", label="DATABASE_URL")

    mensaje = str(excinfo.value)
    assert "No se pudo parsear DATABASE_URL" in mensaje
    assert "S3cr3t" not in mensaje and "shifty_user" not in mensaje


def test_la_api_acepta_la_url_local_con_ssl_disable() -> None:
    """`ssl` es el parametro de asyncpg: llega tal cual; `sslmode` no llega."""
    _, kwargs = PGDialect_asyncpg().create_connect_args(  # type: ignore[no-untyped-call]
        make_url(LOCAL + "?ssl=disable")
    )
    assert kwargs["ssl"] == "disable"
    assert "sslmode" not in kwargs

    engine = create_async_engine(LOCAL + "?ssl=disable")  # sin conectar
    assert engine.dialect.name == "postgresql"


def test_los_dos_consumidores_usan_el_helper_de_core() -> None:
    for archivo in (BACKEND / "run_migrations.py", BACKEND / "alembic" / "env.py"):
        fuente = archivo.read_text(encoding="utf-8")
        assert "def parse_db_url" not in fuente, archivo
        assert re.search(r"from core\.config import [^\n]*\bparse_db_url\b", fuente), (
            archivo
        )


_INTERPOLACION = re.compile(r"\$\{(\w+)(?::-([^}]*)|:\?[^}]*)?\}")


def _resolver(valor: str, entorno: dict[str, str]) -> str:
    """Interpolacion de compose para `${VAR}`, `${VAR:-default}` y `${VAR:?msg}`."""
    return _INTERPOLACION.sub(
        lambda m: entorno.get(m.group(1)) or (m.group(2) or ""), valor
    )


def _urls_de_compose(entorno: dict[str, str]) -> dict[str, str]:
    data = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
    env = data["x-app-environment"]
    return {
        clave: _resolver(str(env[clave]), entorno)
        for clave in ("DATABASE_URL", "MIGRATION_DATABASE_URL")
    }


def test_compose_sin_la_variable_resuelve_ssl_disable() -> None:
    for clave, url in _urls_de_compose({}).items():
        assert url.endswith("?ssl=disable"), (clave, url)
        assert _parse(url)["sslmode"] == "disable"


def test_compose_con_postgres_ssl_resuelve_require() -> None:
    for clave, url in _urls_de_compose({"POSTGRES_SSL": "require"}).items():
        assert url.endswith("?ssl=require"), (clave, url)
        assert _parse(url)["sslmode"] == "require"


def test_ci_y_el_entorno_local_declaran_ssl_disable() -> None:
    """El Postgres de CI y el local no tienen TLS: con `require` por defecto, sin
    esto el job backend-postgres y `run_migrations.py` fallarian al conectar."""
    workflow = yaml.safe_load(
        (RAIZ / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    )
    env = workflow["jobs"]["backend-postgres"]["env"]
    for clave in ("TEST_POSTGRES_MIGRATION_URL", "TEST_POSTGRES_URL"):
        assert str(env[clave]).endswith("?ssl=disable"), clave

    ejemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    url = re.search(r"^DATABASE_URL=(\S+)$", ejemplo, re.MULTILINE)
    assert url is not None and url.group(1).endswith("?ssl=disable")


def test_no_se_toco_el_entorno_real() -> None:
    assert "POSTGRES_SSL" not in os.environ
