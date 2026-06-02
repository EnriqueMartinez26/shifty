from datetime import datetime

from pydantic import BaseModel, Field


class BudgetBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    improvement_description: str = Field(..., min_length=5, max_length=2000)
    estimated_hours: float = Field(..., gt=0, le=10_000)
    hourly_rate: float = Field(..., gt=0, le=10_000_000)
    currency: str = Field(default="ARS", min_length=3, max_length=10)
    status: str = Field(default="draft", min_length=3, max_length=30)
    notes: str | None = Field(None, max_length=2000)


class BudgetCreate(BudgetBase):
    pass


class BudgetUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    improvement_description: str | None = Field(None, min_length=5, max_length=2000)
    estimated_hours: float | None = Field(None, gt=0, le=10_000)
    hourly_rate: float | None = Field(None, gt=0, le=10_000_000)
    currency: str | None = Field(None, min_length=3, max_length=10)
    status: str | None = Field(None, min_length=3, max_length=30)
    notes: str | None = Field(None, max_length=2000)
    is_active: bool | None = None


class BudgetResponse(BudgetBase):
    public_id: str
    total_cost: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
