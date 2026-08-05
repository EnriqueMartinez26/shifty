from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class LedgerMovementCreate(BaseModel):
    movement_type: str = Field(..., pattern=r"^(charge|payment|adjustment|refund)$")
    amount: Decimal = Field(..., ge=0, le=10_000_000, max_digits=12, decimal_places=2)
    appointment_id: str | None = Field(None, max_length=64)
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
