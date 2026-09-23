from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from core.validation import PUBLIC_ID_PATTERN


class LedgerMovementCreate(BaseModel):
    movement_type: str = Field(..., pattern=r"^(charge|payment|adjustment|refund)$")
    amount: Decimal = Field(..., ge=0, le=10_000_000, max_digits=12, decimal_places=2)
    # Misma forma que cualquier id publico; que el turno sea de la tienda lo
    # comprueba el service (AUD2-B2-16).
    appointment_id: str | None = Field(None, max_length=64, pattern=PUBLIC_ID_PATTERN)
    notes: str | None = Field(None, max_length=500)


class LedgerMovementResponse(BaseModel):
    public_id: str
    movement_type: str
    amount: Decimal
    balance_after: Decimal
    appointment_id: str | None = None
    notes: str | None = None
    created_at: datetime


class CustomerLedgerResponse(BaseModel):
    client_id: str
    balance: Decimal
    # Cuantos movimientos tiene el cliente en total: ``movements`` es una
    # pagina, asi que sin esto el panel no sabe si hay mas (AUD2-B2-10).
    total: int
    movements: list[LedgerMovementResponse]


class LedgerSummaryClientItem(BaseModel):
    client_id: str
    client_name: str
    balance: Decimal
    last_movement_at: datetime


class LedgerSummaryResponse(BaseModel):
    total_balance: Decimal
    debtors_count: int
    average_balance: Decimal
    total_movements: int
    top_debtors: list[LedgerSummaryClientItem]
