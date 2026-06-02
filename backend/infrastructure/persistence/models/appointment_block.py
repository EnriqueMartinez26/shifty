from datetime import datetime, timezone
from sqlalchemy import Boolean, String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, synonym
from infrastructure.persistence.models.base import Base
import ulid

class AppointmentBlockModel(Base):
    __tablename__ = "appointment_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(ulid.ULID()))
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.id"), index=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    starts_at = synonym("start_time")
    ends_at = synonym("end_time")

    @property
    def note(self) -> str:
        return self.reason

    def overlaps_with(self, starts_at: datetime, ends_at: datetime) -> bool:
        block_start = self.start_time
        block_end = self.end_time
        if block_start.tzinfo is None:
            block_start = block_start.replace(tzinfo=timezone.utc)
        if block_end.tzinfo is None:
            block_end = block_end.replace(tzinfo=timezone.utc)
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        return block_start < ends_at and block_end > starts_at
