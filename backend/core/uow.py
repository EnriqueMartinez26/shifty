import abc
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# Imports for typing and implementations
from modules.appointments.repository import AppointmentRepository
from modules.audit.repository import AuditRepository


class AbstractUnitOfWork(abc.ABC):
    """
    Interface genérica del Unit of Work.
    La capa de servicio dependerá de esta abstracción y no de SQLAlchemy directamente.
    """

    appointments: AppointmentRepository
    audit: AuditRepository

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            # We don't auto-commit to allow explicit transaction boundaries in service layer.
            pass

    @abc.abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError


class AsyncSqlAlchemyUnitOfWork(AbstractUnitOfWork):
    """
    Implementación concreta de UoW usando SQLAlchemy AsyncSession.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._transaction: Any = None

    async def __aenter__(self) -> "AbstractUnitOfWork":
        # Inicializamos los repositorios inyectando la sesión.
        self.appointments = AppointmentRepository(self.session)
        self.audit = AuditRepository(self.session)
        if not self.session.in_transaction():
            self._transaction = await self.session.begin()
        return await super().__aenter__()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
