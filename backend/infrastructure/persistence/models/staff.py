from datetime import datetime, timezone
from typing import TYPE_CHECKING
from typing import Any

import ulid
from sqlalchemy import Boolean, CheckConstraint, DateTime, String, inspect
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.models.base import Base
from infrastructure.persistence.models.schedule import ScheduleModel

if TYPE_CHECKING:
    from modules.services.model import Service


class StaffModel(Base):
    __tablename__ = "staff"
    __table_args__ = (
        CheckConstraint("kind IN ('person', 'resource')", name="ck_staff_kind"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(ulid.ULID())
    )
    # "person": profesional con usuario de login. "resource": cancha, sala,
    # box... un calendario reservable sin email ni usuario (2026-09-10).
    kind: Mapped[str] = mapped_column(
        String(20), default="person", server_default="person"
    )
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
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

    # Sin carga implicita (F3-01): quien lee franjas o servicios los pide con
    # `selectinload`; un acceso sin cargar revienta en vez de ser una consulta
    # escondida. Con "selectin" cada `select(Staff)` sumaba dos SELECT.
    schedules: Mapped[list["ScheduleModel"]] = relationship(
        "ScheduleModel",
        primaryjoin="StaffModel.id == ScheduleModel.staff_id",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    services: Mapped[list["Service"]] = relationship(
        "Service",
        secondary="staff_services",
        lazy="raise",
    )

    def __init__(self, **kwargs: Any) -> None:
        service_ids = kwargs.pop("service_ids", None)
        super().__init__(**kwargs)
        if service_ids is not None:
            self.service_ids = service_ids

    @property
    def public_id(self) -> str:
        return self.id

    @property
    def service_ids(self) -> list[str]:
        """Servicios del profesional: la coleccion cargada o la lista explicita.

        `services` es `lazy="raise"` (F3-01): sin coleccion ni lista explicita,
        un Staff que ya existe en la base falla fuerte en lugar de decir que no
        tiene servicios. Uno nuevo (sin identidad) todavia no tiene ninguno.
        """
        services = self.__dict__.get("services")
        if services:
            return [
                service.public_id
                for service in services
                if getattr(service, "public_id", None)
            ]
        override = self.__dict__.get("_service_ids_override")
        if override is not None:
            return list(override)
        if services is None and inspect(self).has_identity:
            raise InvalidRequestError(
                "StaffModel.service_ids necesita `services` cargado: la "
                "relacion es lazy='raise', pedila con selectinload(Staff.services)"
            )
        return []

    @service_ids.setter
    def service_ids(self, value: list[str] | None) -> None:
        self._service_ids_override = list(value or [])


STAFF_KIND_PERSON = "person"
STAFF_KIND_RESOURCE = "resource"
