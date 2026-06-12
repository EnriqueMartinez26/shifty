from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from contextvars import ContextVar
from core.config import settings

# ContextVars para aislamiento multi-tenant
_current_store_id: ContextVar[int | None] = ContextVar("current_store_id", default=None)
_is_global_admin: ContextVar[bool] = ContextVar("is_global_admin", default=False)


def set_tenant_context(store_id: int | None, is_admin: bool = False):
    """Establece el contexto del tenant para la sesión actual."""
    _current_store_id.set(store_id)
    _is_global_admin.set(is_admin)


class TenantSession(AsyncSession):
    """
    Sesión estándar de SQLAlchemy. El contexto de tenant se aplica
    en get_db() para evitar reconexiones y efectos laterales por query.
    """


async def _apply_tenant_context(session: AsyncSession) -> None:
    """Aplica el contexto del tenant a la conexión activa de PostgreSQL."""
    store_id = _current_store_id.get()
    is_admin = _is_global_admin.get()

    if store_id is None and not is_admin:
        return

    connection = await session.connection()
    if connection.dialect.name != "postgresql":
        return

    await connection.execute(
        text(
            "SELECT set_config('app.current_store_id', :sid, true), "
            "set_config('app.is_global_admin', :admin, true)"
        ),
        {
            "sid": str(store_id) if store_id else "0",
            "admin": "true" if is_admin else "false",
        },
    )


engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = async_sessionmaker(
    class_=TenantSession,
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Dependency para FastAPI"""
    async with SessionLocal() as session:
        await _apply_tenant_context(session)
        yield session


# Alias para uso fuera de FastAPI (Celery tasks, scripts, etc.)
# Las tareas de Celery usan esto con "async with AsyncSessionFactory() as db:"
AsyncSessionFactory = SessionLocal
