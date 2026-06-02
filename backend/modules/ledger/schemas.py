from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class LedgerMovementCreate(BaseModel):
    movement_type: str = Field(..., pattern=r"^(charge|payment|adjustment|refund)$")
    amount: Decimal = Field(..., ge=0)
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
