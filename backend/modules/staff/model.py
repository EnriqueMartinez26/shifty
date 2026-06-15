from infrastructure.persistence.models.staff import StaffModel as Staff
from infrastructure.persistence.models.schedule import ScheduleModel as Schedule
from infrastructure.persistence.models.appointment_block import (
    AppointmentBlockModel as StaffBlock,
)
from infrastructure.persistence.models.staff_service import StaffServiceModel
from core.models import Base
from sqlalchemy import Column, ForeignKey, String, Table, JSON
import enum

staff_services = Table(
    "staff_services",
    Base.metadata,
    Column(
        "staff_id", String, ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "service_id",
        String,
        ForeignKey("services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    extend_existing=True,
)


class BlockReason(str, enum.Enum):
    VACATION = "vacation"
    SICK_LEAVE = "sick_leave"
    MAINTENANCE = "maintenance"
    TRAINING = "training"
    PERSONAL = "personal"
    OTHER = "other"
