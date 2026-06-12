import uuid
from datetime import datetime
from typing import Optional
from domain.entities.appointment import Appointment, AppointmentStatus
from domain.value_objects.time_slot import TimeSlot
from domain.repositories.appointment_repository import IAppointmentRepository
from domain.exceptions.base_exceptions import ConflictError


class CreateAppointmentUseCase:
    """Use case for creating a new appointment."""

    def __init__(self, repository: IAppointmentRepository):
        self.repository = repository

    async def execute(
        self,
        service_id: str,
        staff_id: str,
        store_id: str,
        start_time: datetime,
        duration_minutes: int,
        client_name: str,
        client_email: Optional[str] = None,
        client_phone: Optional[str] = None,
        notes: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Appointment:
        # 1. Check idempotency
        if idempotency_key:
            existing = await self.repository.find_by_idempotency_key(idempotency_key)
            if existing:
                return existing

        # 2. Create TimeSlot
        time_slot = TimeSlot.from_start_and_duration(start_time, duration_minutes)

        # 3. Check availability (conflict detection)
        # In a real scenario, we might also check 'appointment_blocks'
        staff_appointments = await self.repository.find_by_staff_and_date(
            staff_id, start_time.date()
        )
        for existing in staff_appointments:
            if (
                existing.status != AppointmentStatus.CANCELLED
                and existing.time_slot.overlaps_with(time_slot)
            ):
                raise ConflictError(f"Staff member is already booked at {start_time}")

        # 4. Create Entity
        appointment = Appointment(
            id=str(uuid.uuid4()),
            service_id=service_id,
            staff_id=staff_id,
            store_id=store_id,
            time_slot=time_slot,
            client_name=client_name,
            client_email=client_email,
            client_phone=client_phone,
            notes=notes,
            idempotency_key=idempotency_key,
        )

        # 5. Persist
        return await self.repository.save(appointment)
