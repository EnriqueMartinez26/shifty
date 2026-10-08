"""Acceso a datos de la region de pagos.

Mismo rol que AppointmentRepository: queries puras, sin logica de negocio ni
commit (eso lo maneja el service via el Unit of Work). Existe para que los
casos de uso de pago dejen de hablar con AsyncSession directo desde el router.
"""

from decimal import Decimal

from sqlalchemy import (
    ColumnElement,
    Numeric,
    ScalarSelect,
    and_,
    case,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import (
    ACCREDITED_PAYMENT_STATUSES,
    LIVE_CHARGE_PAYMENT_STATUSES,
    AppointmentBalancePayment,
    JsonValue,
    OutboxMessage,
    Payment,
)

# Columna del turno para correlacionar (``Appointment.id``) o una expresion.
_StrColumn = ColumnElement[str] | InstrumentedAttribute[str]


def live_charge_provider_of(
    appointment_id: _StrColumn | str, store_id: _StrColumn | str
) -> ScalarSelect[str]:
    """``Payment.provider`` del cobro vivo del turno, o NULL si no tiene (D1).

    Unica traduccion a SQL de ``LIVE_CHARGE_PAYMENT_STATUSES``. Recibe valores
    (un turno: ``PaymentRepository.live_charge_provider``) o columnas del
    turno (correlacionado: el historial del cliente lo pone en su mismo
    SELECT, sin una consulta por turno ni una mas por request, regla 12).
    Filtra por ``store_id`` y cae en ``uq_payments_store_appointment`` (un
    cobro por turno).

    Devuelve el proveedor y no solo si existe: la autogestion del cliente
    distingue la sena por WhatsApp (``manual``, que puede cancelar y
    reprogramar) del cobro de Mercado Pago (que no;
    ``public_api.service.client_cancel_denial``).
    """
    return (
        select(Payment.provider)
        .where(
            Payment.store_id == store_id,
            Payment.appointment_id == appointment_id,
            Payment.status.in_(sorted(LIVE_CHARGE_PAYMENT_STATUSES)),
        )
        .limit(1)
        .scalar_subquery()
    )


# Turnos que no deben saldo aunque tengan un cobro acreditado: el ausente no
# recibio el servicio (lo pagado es sena retenida, como lo cuentan los
# reportes) y uno soltado (cancelado o vencido) ya no se cobra (regla 3).
_SIN_SALDO_STATUSES = (
    AppointmentStatus.ABSENT.value,
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.EXPIRED.value,
)


def live_balance_payment_join(
    appointment_id: _StrColumn | str, store_id: _StrColumn | str
) -> ColumnElement[bool]:
    """Condicion de join al resto VIVO del turno (D-20261008-01).

    A lo sumo una fila por turno (``uq_appointment_balance_payments_live``),
    asi que un LEFT JOIN no multiplica turnos, igual que el cobro
    (``uq_payments_store_appointment``). Lleva ``store_id`` por defensa en
    profundidad junto a la RLS (CLAUDE.md §2). Unica definicion para la
    busqueda de Cobros, reportes, panel y el service.
    """
    return and_(
        AppointmentBalancePayment.appointment_id == appointment_id,
        AppointmentBalancePayment.reverted_at.is_(None),
        AppointmentBalancePayment.store_id == store_id,
    )


def remaining_balance_of() -> ColumnElement[Decimal]:
    """Saldo restante del turno, en SQL (regla 11; D-20261008-01).

    Precio congelado - cobro acreditado - resto vivo, sobre un SELECT que ya
    une ``appointments`` con su cobro (``payments``, cualquier estado) y su
    resto vivo (``live_balance_payment_join``). Es cero sin cobro acreditado
    (ahi sigue "Confirmar pago"), sin precio congelado, en un ausente o un
    turno soltado (``_SIN_SALDO_STATUSES``) y si lo pagado ya cubre el precio.
    """
    debe = (
        Appointment.price_amount
        - Payment.amount
        - func.coalesce(AppointmentBalancePayment.amount, 0)
    )
    return case(
        (
            and_(
                Payment.status.in_(sorted(ACCREDITED_PAYMENT_STATUSES)),
                Appointment.status.not_in(_SIN_SALDO_STATUSES),
                debe > 0,
            ),
            debe,
        ),
        else_=literal(Decimal("0.00"), Numeric(12, 2)),
    )


class PaymentRepository:
    """Los accesos a ``payments`` que pasan por el UoW, cada uno con llamador.

    ``live_charge_provider`` (D1, 2026-09-25) lo usa la autogestion del cliente.
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

    async def live_charge_provider(
        self, appointment_id: str, store_id: str
    ) -> str | None:
        """Proveedor del cobro vivo del turno, o None (sin lock: lo lee la
        guarda del cliente, que ya tiene el turno lockeado)."""
        res = await self.db.execute(
            select(live_charge_provider_of(appointment_id, store_id))
        )
        provider = res.scalar()
        return None if provider is None else str(provider)


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


class BalancePaymentRepository:
    """Acceso a ``appointment_balance_payments`` (D-20261008-01).

    Consultas puras: la regla (cuando se registra y por cuanto) y el commit
    son del service (``payments.application.PaymentService``).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, balance_payment: AppointmentBalancePayment) -> None:
        self.db.add(balance_payment)

    async def get_live(
        self, appointment_id: str, store_id: str, *, lock: bool = False
    ) -> AppointmentBalancePayment | None:
        """El resto vivo del turno, o None. Con ``lock`` lo toma ``FOR
        UPDATE``: quien lo llama ya tiene el turno lockeado (regla 7)."""
        query = select(AppointmentBalancePayment).where(
            live_balance_payment_join(appointment_id, store_id)
        )
        if lock:
            query = query.with_for_update()
        return (await self.db.execute(query)).scalar_one_or_none()

    async def remaining_balance(self, appointment_id: str, store_id: str) -> Decimal:
        """Saldo restante del turno (``remaining_balance_of``), una sentencia."""
        saldo = await self.db.scalar(
            select(remaining_balance_of())
            .select_from(Appointment)
            .outerjoin(
                Payment,
                and_(
                    Payment.appointment_id == Appointment.id,
                    Payment.store_id == store_id,
                ),
            )
            .outerjoin(
                AppointmentBalancePayment,
                live_balance_payment_join(Appointment.id, store_id),
            )
            .where(Appointment.id == appointment_id, Appointment.store_id == store_id)
        )
        return Decimal(str(saldo or 0))
