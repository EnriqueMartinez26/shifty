from modules.services.schemas import ServiceResponse
from modules.staff.model import Schedule, Staff
from modules.staff.schemas import ScheduleResponse, StaffResponse


def to_schedule_response(schedule: Schedule) -> ScheduleResponse:
    return ScheduleResponse.model_validate(schedule)


def to_staff_response(member: Staff) -> StaffResponse:
    return StaffResponse(
        public_id=member.public_id,
        display_name=member.display_name,
        first_name=member.first_name or "",
        last_name=member.last_name or "",
        email=member.email,
        is_active=member.is_active,
        service_ids=member.service_ids or [],
        services=[
            ServiceResponse.model_validate(service) for service in member.services
        ],
        schedules=[to_schedule_response(schedule) for schedule in member.schedules],
    )
