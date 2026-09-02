from contextvars import ContextVar
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

# ContextVars para aislamiento multi-tenant
_current_store_id: ContextVar[str | None] = ContextVar("current_store_id", default=None)
_is_global_admin: ContextVar[bool] = ContextVar("is_global_admin", default=False)


def set_tenant_context(store_id: str | None, is_admin: bool = False) -> None:
    """Establece el contexto del tenant para la sesión actual."""
    _current_store_id.set(store_id)
    _is_global_admin.set(is_admin)


class TenantSession(AsyncSession):
    """Sesion que mantiene vivo el contexto de tenant entre transacciones.

    ``set_config(..., is_local => true)`` vive dentro de la transaccion actual:
    al hacer commit se pierde. Como despues del commit suele venir un refresh o
    una lectura, esa consulta abria una transaccion nueva sin ``store_id`` y las
    politicas de RLS la filtraban entera.

    Mientras el rol de base era superusuario con BYPASSRLS esto no se notaba,
    porque RLS no se aplicaba a nadie. Con un rol restringido, reaplicar el
    contexto despues de cada commit y rollback es lo que sostiene la sesion.
    """

    async def commit(self) -> None:
        await super().commit()
        await _apply_tenant_context(self)

    async def rollback(self) -> None:
        await super().rollback()
        await _apply_tenant_context(self)


async def _apply_tenant_context(session: AsyncSession) -> None:
    """Aplica el contexto del tenant a la conexión activa de PostgreSQL.

    Siempre escribe ambos settings, incluso vacíos. Antes, con contexto
    (None, False) se salteaba el set_config: un "reset" no reseteaba nada y un
    contexto admin previo podía quedar pegado en la transacción.
    """
    store_id = _current_store_id.get()
    is_admin = _is_global_admin.get()

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


# El pool solo se dimensiona para PostgreSQL. SQLite (tests) usa StaticPool,
# que no acepta pool_size ni max_overflow.
_engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
if settings.DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    class_=TenantSession,
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependency para FastAPI"""
    async with SessionLocal() as session:
        await _apply_tenant_context(session)
        yield session


# Alias para uso fuera de FastAPI (Celery tasks, scripts, etc.)
# Las tareas de Celery usan esto con "async with AsyncSessionFactory() as db:"
AsyncSessionFactory = SessionLocal
