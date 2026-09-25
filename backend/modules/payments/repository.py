"""Acceso a datos de la region de pagos.

Mismo rol que AppointmentRepository: queries puras, sin logica de negocio ni
commit (eso lo maneja el service via el Unit of Work). Existe para que los
casos de uso de pago dejen de hablar con AsyncSession directo desde el router.
"""

from sqlalchemy import ColumnElement, Exists, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from modules.payments.model import (
    LIVE_CHARGE_PAYMENT_STATUSES,
    JsonValue,
    OutboxMessage,
    Payment,
)

# Columna del turno para correlacionar (``Appointment.id``) o una expresion.
_StrColumn = ColumnElement[str] | InstrumentedAttribute[str]


def live_charge_of(
    appointment_id: _StrColumn | str, store_id: _StrColumn | str
) -> Exists:
    """``EXISTS`` de un cobro vivo del turno (decision D1, 2026-09-25).

    Unica traduccion a SQL de ``LIVE_CHARGE_PAYMENT_STATUSES``. Recibe valores
    (un turno: ``PaymentRepository.has_live_charge``) o columnas del turno
    (correlacionado: el historial del cliente lo pone en su mismo SELECT, sin
    una consulta por turno ni una mas por request, regla 12). Filtra por
    ``store_id`` y cae en ``uq_payments_store_appointment``.
    """
    return exists().where(
        Payment.store_id == store_id,
        Payment.appointment_id == appointment_id,
        Payment.status.in_(sorted(LIVE_CHARGE_PAYMENT_STATUSES)),
    )


class PaymentRepository:
    """Los accesos a ``payments`` que pasan por el UoW, cada uno con llamador.

    ``has_live_charge`` (D1, 2026-09-25) lo usa la autogestion del cliente.
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

    async def has_live_charge(self, appointment_id: str, store_id: str) -> bool:
        """Si el turno tiene un cobro vivo (sin lock: lo lee la guarda del
        cliente, que ya tiene el turno lockeado)."""
        res = await self.db.execute(select(live_charge_of(appointment_id, store_id)))
        return bool(res.scalar())


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
