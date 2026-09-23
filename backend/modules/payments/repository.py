"""Acceso a datos de la region de pagos.

Mismo rol que AppointmentRepository: queries puras, sin logica de negocio ni
commit (eso lo maneja el service via el Unit of Work). Existe para que los
casos de uso de pago dejen de hablar con AsyncSession directo desde el router.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.model import OutboxMessage, JsonValue, Payment


class PaymentRepository:
    """Un solo metodo: el unico acceso a ``payments`` que pasa por el UoW.

    Tenia tres mas (``get_by_appointment``, ``get_by_public_id``, ``add``) sin
    ningun llamador, ni en produccion ni en tests: aparentaban una API que
    nadie ejercia (AUD2-B2-13, 2026-09-20). El resto de los caminos de pago
    todavia consulta con ``select`` directo; cuando migren, el metodo que
    necesiten se agrega con su llamador en el mismo commit.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_appointment_locked(
        self, appointment_id: str, store_id: str
    ) -> Payment | None:
        """Pago del turno con bloqueo pesimista (para liberar/reembolsar)."""
        res = await self.db.execute(
            select(Payment)
            .where(
                Payment.appointment_id == appointment_id,
                Payment.store_id == store_id,
            )
            .with_for_update()
        )
        return res.scalar_one_or_none()


class OutboxRepository:
    """Publica eventos de dominio en el outbox transaccional."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def publish(
        self, *, store_id: str, event_type: str, payload: dict[str, JsonValue]
    ) -> None:
        self.db.add(
            OutboxMessage(
                store_id=store_id,
                event_type=event_type,
                payload=payload,
            )
        )
