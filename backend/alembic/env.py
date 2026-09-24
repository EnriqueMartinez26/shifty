"""
Alembic migration environment.

Usa psycopg2 (sync) en lugar de asyncpg para evitar el bug WinError 64
con el ProactorEventLoop de Python 3.13 en Windows.
"""

from logging.config import fileConfig
from sqlalchemy import Engine, create_engine, pool
from sqlalchemy.engine import URL
from alembic import context

# Base + TODOS los modelos, desde el registro unico: una lista parcial hace
# que autogenerate proponga borrar las tablas que no vio.
# Unica lectura de la URL del repo (B7-11): lee `ssl`, acepta `sslmode` y
# usa `require` cuando falta. Antes esta copia tenia `disable` por defecto
# y no leia `ssl`: la URL de produccion `?ssl=require` migraba sin TLS.
from core.config import parse_db_url, settings
from core.model_registry import load_all_models
from core.models import Base

load_all_models()

# Alembic Config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# F0-06 (plan de rendimiento): una migracion que espera un lock fuerte encola
# detras de ella TODAS las consultas de la app sobre esa tabla, asi que el
# deploy tumbaba la API sin que la migracion hiciera nada. Con este tope aborta
# a los 3 s y el deploy falla a la vista, con el codigo viejo sirviendo; se
# reintenta con la tabla tranquila. `statement_timeout` en 0: un backfill por
# lotes legitimo no puede cortarse por un timeout heredado de la sesion.
MIGRATION_SESSION_SETTINGS = (
    "SET lock_timeout = '3s'",
    "SET statement_timeout = 0",
)


def get_sync_engine() -> Engine:
    """
    Crea un engine síncrono con psycopg2 usando parámetros explícitos.
    Evita el UnicodeDecodeError al no construir un DSN string.
    """
    params = parse_db_url(
        settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL,
        label="MIGRATION_DATABASE_URL",
    )

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
    params = parse_db_url(
        settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL,
        label="MIGRATION_DATABASE_URL",
    )
    # `parse_db_url` devuelve usuario y password ya des-escapados (`unquote`).
    # Rearmar la URL con un f-string los dejaba crudos: una password con `@`,
    # `/`, `:`, `?` o `#` producia una URL que SQLAlchemy leia como otro
    # usuario, otro host y otra base, y el error resultante podia llevarla
    # entera (regla 20). `URL.create` re-escapa cada componente
    # (AUD2-B7-10). El modo online no pasa por aca: usa `connect_args`.
    url = URL.create(
        "postgresql+psycopg2",
        username=params["user"],
        password=params["password"],
        host=params["host"],
        port=params["port"],
        database=params["dbname"],
    )
    context.configure(
        url=url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode con psycopg2 (sync)."""
    connectable = get_sync_engine()

    with connectable.connect() as connection:
        for sentencia in MIGRATION_SESSION_SETTINGS:
            connection.exec_driver_sql(sentencia)
        # Los SET abren una transaccion (autobegin de SQLAlchemy 2). Abierta al
        # configurar, Alembic la toma como externa: no abre una por migracion y
        # no commitea nada. Los SET son de sesion y sobreviven al commit.
        connection.commit()
        # Cada revision en su transaccion: una cadena larga no retiene los
        # locks de la primera hasta la ultima, y un fallo en la sexta deja
        # aplicadas y registradas las cinco anteriores.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
