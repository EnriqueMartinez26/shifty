"""Acceso a datos de la region de pagos.

Mismo rol que AppointmentRepository: queries puras, sin logica de negocio ni
commit (eso lo maneja el service via el Unit of Work). Existe para que los
casos de uso de pago dejen de hablar con AsyncSession directo desde el router.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.model import OutboxMessage, JsonValue, Payment


class PaymentRepository:
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

    async def get_by_public_id(self, payment_id: str, store_id: str) -> Payment | None:
        res = await self.db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.store_id == store_id,
            )
        )
        return res.scalar_one_or_none()

    def add(self, payment: Payment) -> None:
        self.db.add(payment)


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
