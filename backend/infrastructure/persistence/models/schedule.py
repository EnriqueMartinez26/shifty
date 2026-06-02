from datetime import time, timezone, datetime
from sqlalchemy import String, ForeignKey, Integer, Time, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.models.base import Base
import ulid

class ScheduleModel(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(ulid.ULID()))
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.id"), index=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer) # 0-6
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @property
    def public_id(self) -> str:
        return self.id
