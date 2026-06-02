from typing import List, Optional
from datetime import date, datetime, time
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from domain.entities.appointment import Appointment, AppointmentStatus
from domain.value_objects.time_slot import TimeSlot
from domain.repositories.appointment_repository import IAppointmentRepository
from infrastructure.persistence.models.appointment import AppointmentModel

class AppointmentRepository(IAppointmentRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_id(self, id: str) -> Optional[Appointment]:
        stmt = select(AppointmentModel).where(AppointmentModel.id == id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._map_to_entity(model) if model else None

    async def find_by_date(self, store_id: str, date_val: date) -> List[Appointment]:
        start = datetime.combine(date_val, time.min)
        end = datetime.combine(date_val, time.max)
        stmt = select(AppointmentModel).where(
            and_(
                AppointmentModel.store_id == store_id,
                AppointmentModel.starts_at >= start,
                AppointmentModel.starts_at <= end
            )
        )
        result = await self.session.execute(stmt)
        return [self._map_to_entity(m) for m in result.scalars().all()]

    async def find_by_staff_and_date(self, staff_id: str, date_val: date) -> List[Appointment]:
        start = datetime.combine(date_val, time.min)
        end = datetime.combine(date_val, time.max)
        stmt = select(AppointmentModel).where(
            and_(
                AppointmentModel.staff_id == staff_id,
                AppointmentModel.starts_at >= start,
                AppointmentModel.starts_at <= end
            )
        )
        result = await self.session.execute(stmt)
        return [self._map_to_entity(m) for m in result.scalars().all()]

    async def find_by_idempotency_key(self, key: str) -> Optional[Appointment]:
        stmt = select(AppointmentModel).where(AppointmentModel.idempotency_key == key)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._map_to_entity(model) if model else None

    async def save(self, appointment: Appointment) -> Appointment:
        model = await self.session.get(AppointmentModel, appointment.id)
        
        if not model:
            model = AppointmentModel(
                id=appointment.id,
                service_id=appointment.service_id,
                staff_id=appointment.staff_id,
                store_id=appointment.store_id,
                starts_at=appointment.time_slot.start_time,
                duration_minutes=appointment.time_slot.duration_minutes,
                client_name=appointment.client_name,
                client_email=appointment.client_email,
                client_phone=appointment.client_phone,
                status=appointment.status.value,
                notes=appointment.notes,
                idempotency_key=appointment.idempotency_key,
                created_at=appointment.created_at,
                updated_at=appointment.updated_at
            )
            self.session.add(model)
        else:
            # Update existing model
            model.starts_at = appointment.time_slot.start_time
            model.duration_minutes = appointment.time_slot.duration_minutes
            model.status = appointment.status.value
            model.notes = appointment.notes
            model.updated_at = datetime.utcnow()

        await self.session.flush()
        return self._map_to_entity(model)

    def _map_to_entity(self, model: AppointmentModel) -> Appointment:
        return Appointment(
            id=model.id,
            service_id=model.service_id,
            staff_id=model.staff_id,
            store_id=model.store_id,
            time_slot=TimeSlot.from_start_and_duration(model.starts_at, model.duration_minutes),
            client_name=model.client_name,
            client_email=model.client_email,
            client_phone=model.client_phone,
            status=AppointmentStatus(model.status),
            notes=model.notes,
            idempotency_key=model.idempotency_key,
            created_at=model.created_at,
            updated_at=model.updated_at
        )
