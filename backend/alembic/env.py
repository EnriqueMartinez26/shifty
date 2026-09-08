"""
Alembic migration environment.

Usa psycopg2 (sync) en lugar de asyncpg para evitar el bug WinError 64
con el ProactorEventLoop de Python 3.13 en Windows.
"""

from urllib.parse import parse_qs, unquote, urlparse
from logging.config import fileConfig
from typing import Any
from sqlalchemy import Engine, create_engine, pool
from alembic import context

# Base + TODOS los modelos, desde el registro unico: una lista parcial hace
# que autogenerate proponga borrar las tablas que no vio.
from core.config import settings
from core.model_registry import load_all_models
from core.models import Base

load_all_models()

# Alembic Config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def parse_db_url(url: str) -> dict[str, Any]:
    """
    Parsea la DATABASE_URL y extrae los componentes.
    Soporta formato: postgresql+asyncpg://user:pass@host:port/db
    """
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme != "postgresql" or not parsed.hostname or not parsed.path:
        raise ValueError(f"No se pudo parsear DATABASE_URL: {url}")

    query = parse_qs(parsed.query)
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "dbname": parsed.path.lstrip("/"),
        "sslmode": query.get("sslmode", ["disable"])[0],
    }


def get_sync_engine() -> Engine:
    """
    Crea un engine síncrono con psycopg2 usando parámetros explícitos.
    Evita el UnicodeDecodeError al no construir un DSN string.
    """
    params = parse_db_url(settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL)

    engine = create_engine(
        "postgresql+psycopg2://",
        connect_args={
            "host": params["host"],
            "port": params["port"],
            "user": params["user"],
            "password": params["password"],
            "dbname": params["dbname"],
            "sslmode": params["sslmode"],
            "client_encoding": "utf8",
        },
        poolclass=pool.NullPool,
    )
    return engine


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    params = parse_db_url(settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL)
    url = (
        f"postgresql+psycopg2://{params['user']}:{params['password']}"
        f"@{params['host']}:{params['port']}/{params['dbname']}"
    )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode con psycopg2 (sync)."""
    connectable = get_sync_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
