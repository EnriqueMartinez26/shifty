import abc
from sqlalchemy.ext.asyncio import AsyncSession

# Imports for typing and implementations
from modules.appointments.repository import AppointmentRepository
from modules.audit.service import AuditService


class AbstractUnitOfWork(abc.ABC):
    """
    Interface genérica del Unit of Work.
    La capa de servicio dependerá de esta abstracción y no de SQLAlchemy directamente.
    """

    appointments: AppointmentRepository
    audit: (
        AuditService  # TODO: Podría extraerse a AuditRepository también para limpieza
    )

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.rollback()
        else:
            # We don't auto-commit to allow explicit transaction boundaries in service layer.
            pass

    @abc.abstractmethod
    async def commit(self):
        raise NotImplementedError

    @abc.abstractmethod
    async def rollback(self):
        raise NotImplementedError


class AsyncSqlAlchemyUnitOfWork(AbstractUnitOfWork):
    """
    Implementación concreta de UoW usando SQLAlchemy AsyncSession.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._transaction = None

    async def __aenter__(self) -> "AbstractUnitOfWork":
        # Inicializamos los repositorios inyectando la sesión.
        self.appointments = AppointmentRepository(self.session)
        # AuditService aún tiene responsabilidades mixtas pero funciona como Repositorio para la creación de logs.
        self.audit = AuditService(self.session)
        if not self.session.in_transaction():
            self._transaction = await self.session.begin()
        return await super().__aenter__()

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
