from decimal import Decimal
import enum

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class LedgerMovementType(str, enum.Enum):
    CHARGE = "charge"
    PAYMENT = "payment"
    ADJUSTMENT = "adjustment"
    REFUND = "refund"


class CustomerLedger(BaseEntity):
    __tablename__ = "customer_ledger"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Si este movimiento anula a otro, apunta al id del movimiento original.
    # Sirve de candado: un movimiento no puede revertirse dos veces.
    reverses_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_ledger.id"), nullable=True, index=True
    )

    @staticmethod
    def signed(movement_type: str, amount: Decimal) -> Decimal:
        """Efecto con signo sobre el saldo: cobros suman, pagos/devoluciones restan.

        Un 'adjustment' respeta el signo del monto (puede ser negativo), lo que
        permite que una reversa reste sin inventar un tipo nuevo.
        """
        if movement_type in {
            LedgerMovementType.PAYMENT.value,
            LedgerMovementType.REFUND.value,
        }:
            return -amount
        return amount

    @property
    def signed_amount(self) -> Decimal:
        return self.signed(self.movement_type, self.amount)

    @property
    def is_reversal(self) -> bool:
        return self.reverses_id is not None

    def build_reversal(self, *, balance_after: Decimal) -> "CustomerLedger":
        """Crea el movimiento que anula a este.

        El ajuste niega el efecto del original (mismo modulo, signo opuesto) y
        deja ``reverses_id`` apuntando al origen: ese es el candado que impide
        revertirlo dos veces. No borra el original: preserva la trazabilidad del
        saldo.
        """
        return CustomerLedger(
            store_id=self.store_id,
            client_id=self.client_id,
            appointment_id=self.appointment_id,
            movement_type=LedgerMovementType.ADJUSTMENT.value,
            amount=-self.signed_amount,
            balance_after=balance_after,
            notes=f"Reversa de movimiento {self.id}",
            reverses_id=self.id,
        )
