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

# Importar Base y modelos para autogenerate
from core.models import Base

# from modules.users.model import User
from modules.stores.model import Store
from modules.services.model import Service

# from modules.staff.model import Staff, Schedule, StaffBlock
# from modules.appointments.model import Appointment
from modules.budget.model import Budget
from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.audit.model import AuditLog
from infrastructure.persistence.models.appointment import AppointmentModel
from infrastructure.persistence.models.staff import StaffModel
from infrastructure.persistence.models.user import UserModel
from infrastructure.persistence.models.appointment_block import AppointmentBlockModel
from infrastructure.persistence.models.staff_service import StaffServiceModel
from infrastructure.persistence.models.schedule import ScheduleModel
from core.config import settings

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
