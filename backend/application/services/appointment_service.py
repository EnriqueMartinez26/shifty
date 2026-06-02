from typing import List, Optional
from datetime import date
from application.dtos.appointment_dtos import CreateAppointmentRequest, AppointmentResponse
from domain.use_cases.appointments.create_appointment import CreateAppointmentUseCase
from domain.repositories.appointment_repository import IAppointmentRepository
from domain.repositories.staff_repository import IStaffRepository
from domain.exceptions.base_exceptions import EntityNotFoundError

class AppointmentService:
    def __init__(self, repository: IAppointmentRepository, staff_repository: IStaffRepository):
        self.repository = repository
        self.staff_repository = staff_repository
        self.create_use_case = CreateAppointmentUseCase(repository)

    async def get_by_id(self, appointment_id: str) -> AppointmentResponse:
        appointment = await self.repository.find_by_id(appointment_id)
        if not appointment:
            raise EntityNotFoundError(f"Appointment {appointment_id} not found")
        return self._map_to_response(appointment)

    async def list_by_date(self, store_id: str, date_val: date) -> List[AppointmentResponse]:
        appointments = await self.repository.find_by_date(store_id, date_val)
        return [self._map_to_response(a) for a in appointments]

    async def create(self, request: CreateAppointmentRequest, store_id: str) -> AppointmentResponse:
        appointment = await self.create_use_case.execute(
            service_id=request.service_id,
            staff_id=request.staff_id,
            store_id=store_id,
            start_time=request.start_time,
            duration_minutes=request.duration_minutes,
            client_name=request.client_name,
            client_email=request.client_email,
            client_phone=request.client_phone,
            notes=request.notes,
            idempotency_key=request.idempotency_key
        )
        return self._map_to_response(appointment)

    async def confirm(self, appointment_id: str) -> AppointmentResponse:
        appointment = await self.repository.find_by_id(appointment_id)
        if not appointment:
            raise EntityNotFoundError(f"Appointment {appointment_id} not found")
        
        appointment.confirm()
        saved = await self.repository.save(appointment)
        return self._map_to_response(saved)

    def _map_to_response(self, appointment) -> AppointmentResponse:
        return AppointmentResponse(
            id=appointment.id,
            service_id=appointment.service_id,
            staff_id=appointment.staff_id,
            store_id=appointment.store_id,
            start_time=appointment.time_slot.start_time,
            end_time=appointment.time_slot.end_time,
            duration_minutes=appointment.time_slot.duration_minutes,
            client_name=appointment.client_name,
            client_email=appointment.client_email,
            client_phone=appointment.client_phone,
            status=appointment.status.value,
            notes=appointment.notes,
            created_at=appointment.created_at,
            updated_at=appointment.updated_at
        )
