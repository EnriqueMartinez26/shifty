from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class Budget(BaseEntity):
    __tablename__ = "budgets"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    improvement_description: Mapped[str] = mapped_column(Text)
    estimated_hours: Mapped[float] = mapped_column(Numeric(10, 2))
    hourly_rate: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="ARS")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def total_cost(self) -> float:
        if self.estimated_hours is None or self.hourly_rate is None:
            return 0.0
        return float(self.estimated_hours) * float(self.hourly_rate)
