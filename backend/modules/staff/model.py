from infrastructure.persistence.models.staff import StaffModel as Staff
from infrastructure.persistence.models.schedule import ScheduleModel as Schedule
from infrastructure.persistence.models.appointment_block import (
    AppointmentBlockModel as StaffBlock,
)
from infrastructure.persistence.models.staff_service import StaffServiceModel
from sqlalchemy import Table
from typing import cast
import enum

# Alias de la tabla del modelo ORM, no una redeclaracion (B3-20). Antes era un
# Table(..., extend_existing=True) sobre la misma MetaData y sin la columna
# rating, que solo funcionaba porque el import de arriba corria primero.
# __table__ esta tipado como FromClause; en un modelo declarativo es la Table.
staff_services = cast(Table, StaffServiceModel.__table__)


class BlockReason(str, enum.Enum):
    VACATION = "vacation"
    SICK_LEAVE = "sick_leave"
    MAINTENANCE = "maintenance"
    TRAINING = "training"
    PERSONAL = "personal"
    OTHER = "other"


__all__ = [
    "BlockReason",
    "Schedule",
    "Staff",
    "StaffBlock",
    "StaffServiceModel",
    "staff_services",
]
