from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from infrastructure.persistence.models.base import Base
from infrastructure.persistence.models.schedule import ScheduleModel
import ulid

class StaffModel(Base):
    __tablename__ = "staff"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(ulid.ULID()))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), index=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    service_ids: Mapped[List[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relación real con ScheduleModel
    schedules: Mapped[list["ScheduleModel"]] = relationship(
        "ScheduleModel",
        primaryjoin="StaffModel.id == ScheduleModel.staff_id",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def public_id(self) -> str:
        return self.id

    @property
    def user(self):
        return None

    @property
    def services(self):
        if not hasattr(self, "_services"):
            self._services = []
        return self._services

    @services.setter
    def services(self, value):
        self._services = value
