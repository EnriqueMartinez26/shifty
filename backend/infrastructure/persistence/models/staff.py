from datetime import datetime, timezone
from typing import TYPE_CHECKING

import ulid
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.models.base import Base
from infrastructure.persistence.models.schedule import ScheduleModel

if TYPE_CHECKING:
    from modules.services.model import Service


class StaffModel(Base):
    __tablename__ = "staff"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(ulid.ULID())
    )
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), index=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    schedules: Mapped[list["ScheduleModel"]] = relationship(
        "ScheduleModel",
        primaryjoin="StaffModel.id == ScheduleModel.staff_id",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    services: Mapped[list["Service"]] = relationship(
        "Service",
        secondary="staff_services",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        service_ids = kwargs.pop("service_ids", None)
        super().__init__(**kwargs)
        if service_ids is not None:
            self.service_ids = service_ids

    @property
    def public_id(self) -> str:
        return self.id

    @property
    def service_ids(self) -> list[str]:
        services = self.__dict__.get("services") or []
        if services:
            return [
                service.public_id
                for service in services
                if getattr(service, "public_id", None)
            ]
        override = getattr(self, "_service_ids_override", None)
        return list(override) if override is not None else []

    @service_ids.setter
    def service_ids(self, value: list[str] | None) -> None:
        self._service_ids_override = list(value or [])
