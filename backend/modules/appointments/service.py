"""
Capa de Servicios de Turnos (AppointmentService).

Responsabilidades:
- Orquestación de la lógica de negocio (crear, cancelar, confirmar, completar).
- Coordinación entre repositorios, auditoría y notificaciones.
- Los repositorios son solo "colecciones de datos"; la inteligencia está aquí.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from core.uow import AbstractUnitOfWork
import ulid

from core.exceptions import (
    AppointmentConflictException,
    AppointmentNotFoundException,
    BlockedScheduleException,
    ResourceNotFoundException,
    BookingNoticeException,
)
from modules.appointments.domain_service import SchedulingDomainService
from modules.appointments.model import Appointment, AppointmentStatus
from modules.audit.model import AuditAction
from modules.notifications.tasks import send_appointment_confirmation
from modules.services.model import Service
from modules.staff.model import Staff, StaffBlock
from modules.users.model import User

if TYPE_CHECKING:
    pass


class AppointmentService:
    """
    Servicio principal de turnos.
    Se instancia por request, inyectando db y redis desde FastAPI Depends.
    """

    def __init__(self, uow: AbstractUnitOfWork, redis: Redis) -> None:
        self.uow = uow
        self.redis = redis
        self.scheduler = SchedulingDomainService()

    # ------------------------------------------------------------------
    # Crear turno
    # ------------------------------------------------------------------

    async def book(
        self,
        *,
        data: dict,
        store_id: int,
        actor: User,
    ) -> tuple[Appointment, Service, Staff]:
        """
        Crea un nuevo turno con:
          1. Resolución de servicio y staff.
          2. Verificación de bloqueos de agenda (StaffBlock).
          3. Bloqueo pesimista (FOR UPDATE) + verificación de conflictos.
          4. Inserción atómica + registro de auditoría.
          5. Disparo de notificación por email (Celery, fuera de la transacción).
        """
        # 1. Resolver entidades -----------------------------------------
        service = await self.uow.appointments.get_service_by_public_id(data["service_id"])
        if not service:
            raise ResourceNotFoundException("Servicio", data["service_id"])

        staff = await self.uow.appointments.get_staff_by_public_id(data["staff_id"])
        if not staff:
            raise ResourceNotFoundException("Profesional", data["staff_id"])

        starts_at: datetime = data["starts_at"]
        ends_at: datetime = starts_at + timedelta(minutes=service.duration_minutes)

        # 1.5. Verificar Forcing Function: min_booking_notice_hours
        store = await self.uow.appointments.get_store_by_id(store_id)
        notice_hours = getattr(store, "min_booking_notice_hours", 2)
        now_utc = datetime.now(timezone.utc)
        if starts_at < now_utc + timedelta(hours=notice_hours):
            raise BookingNoticeException(notice_hours)

        # 2. Verificar bloqueos de agenda --------------------------------
        block = await self.uow.appointments.get_overlapping_block(staff.id, starts_at, ends_at)
        
        # 3. Bloqueo pesimista + verificación de conflictos --------------
        await self.uow.appointments.lock_staff_row(staff.id)
        conflict = await self.uow.appointments.get_conflicting_appointment(staff.id, starts_at, ends_at)

        # Delegar validación al Domain Service (DDD + UX Feedback)
        try:
            self.scheduler.validate_availability(
                requested_start=starts_at,
                requested_end=ends_at,
                conflicting_appointment=conflict,
                overlapping_block=block
            )
        except (AppointmentConflictException, BlockedScheduleException) as e:
            # Don Norman: Si hay error, busca una alternativa inmediata
            # Buscamos desde el fin del conflicto o bloqueo
            search_start = conflict.ends_at if conflict else block.ends_at
            suggestion = await self._find_suggestion(staff.id, search_start, service.duration_minutes)
            
            # Re-lanzar con la sugerencia
            if isinstance(e, AppointmentConflictException):
                raise AppointmentConflictException(
                    conflict_start=conflict.starts_at,
                    conflict_end=conflict.ends_at,
                    suggestion=suggestion
                )
            else:
                raise BlockedScheduleException(
                    reason=block.note,
                    block_start=block.starts_at,
                    block_end=block.ends_at,
                    suggestion=suggestion
                )

        # 4. Creación atómica con auditoría ------------------------------
        appointment = Appointment(
            id=str(ulid.ULID()),
            store_id=store_id,
            staff_id=staff.id,
            service_id=service.id,
            client_id=actor.id,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=service.duration_minutes,
            client_name=(f"{actor.first_name or ''} {actor.last_name or ''}".strip() or actor.email),
            client_email=actor.email,
            client_phone=actor.phone,
            notes=data.get("notes"),
            intake_answers=data.get("intake_answers") or {},
            idempotency_key=data.get("idempotency_key"),
        )
        self.uow.appointments.add(appointment)

        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_after={
                "status": appointment.status,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "service_id": service.public_id,
                "staff_id": staff.public_id,
            },
        )

        await self.uow.commit()

        # 5. Notificación (fuera de transacción, no blocking) ---------------
        send_appointment_confirmation.delay(
            email=actor.email,
            details={
                "public_id": appointment.public_id,
                "service": service.name,
                "staff": staff.display_name,
                "date": starts_at.isoformat(),
            },
        )

        # Invalidar caché de disponibilidad
        cache_key = f"availability:{store_id}:{service.public_id}:{starts_at.date().isoformat()}"
        await self.redis.delete(cache_key)

        return appointment, service, staff

    # ------------------------------------------------------------------
    # Cambios de estado
    # ------------------------------------------------------------------

    async def cancel(self, *, public_id: str, actor: User) -> Appointment:
        """Cancela un turno verificando la transición de estado."""
        appointment = await self.uow.appointments.get_by_public_id(public_id)
        if not appointment:
            raise AppointmentNotFoundException(public_id)

        payload_before = {"status": appointment.status}

        # El modelo valida internamente la transición (lanza excepción si inválida)
        appointment.apply_status_transition(AppointmentStatus.CANCELLED)

        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status},
        )

        await self.uow.commit()

        # Invalidar caché de disponibilidad
        cache_key = f"availability:{appointment.store_id}:*:{appointment.starts_at.date().isoformat()}"
        await self.redis.delete(cache_key)

        return appointment

    async def confirm(self, *, public_id: str, actor: User) -> Appointment:
        """Confirma un turno (solo ADMIN o STAFF)."""
        appointment = await self.uow.appointments.get_by_public_id(public_id)
        if not appointment:
            raise AppointmentNotFoundException(public_id)

        payload_before = {"status": appointment.status}
        appointment.apply_status_transition(AppointmentStatus.CONFIRMED)

        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status},
        )

        await self.uow.commit()
        return appointment

    async def complete(self, *, public_id: str, actor: User) -> Appointment:
        """Marca un turno como completado."""
        appointment = await self.uow.appointments.get_by_public_id(public_id)
        if not appointment:
            raise AppointmentNotFoundException(public_id)

        payload_before = {"status": appointment.status}
        appointment.apply_status_transition(AppointmentStatus.COMPLETED)

        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status, "completed_at": appointment.completed_at.isoformat() if appointment.completed_at else None},
        )

        await self.uow.commit()
        return appointment

    async def mark_absent(self, *, public_id: str, actor: User) -> Appointment:
        """
        Marca el turno como AUSENTE (cliente no se presentó).
        Solo aplicable desde CONFIRMED.
        """
        appointment = await self.uow.appointments.get_by_public_id(public_id)
        if not appointment:
            raise AppointmentNotFoundException(public_id)

        payload_before = {"status": appointment.status}
        appointment.apply_status_transition(AppointmentStatus.ABSENT)

        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status},
        )

        await self.uow.commit()
        return appointment

    async def update_staff_notes(
        self, *, public_id: str, notes_staff: str, actor: User
    ) -> Appointment:
        """
        Actualiza las notas del profesional sobre el turno.
        Solo STAFF o ADMIN pueden editar estas notas.
        """
        appointment = await self.uow.appointments.get_by_public_id(public_id)
        if not appointment:
            raise AppointmentNotFoundException(public_id)

        payload_before = {"notes_staff": appointment.notes_staff}
        appointment.notes_staff = notes_staff

        await self.uow.audit.log(
            action=AuditAction.UPDATE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"notes_staff": notes_staff},
        )

        await self.uow.commit()
        return appointment

    async def reschedule(
        self,
        *,
        public_id: str,
        new_starts_at: datetime,
        idempotency_key: str,
        actor: User,
    ) -> tuple[Appointment, Service, Staff]:
        """
        Reprograma un turno: cancela el original y crea uno nuevo.

        Implementación:
          1. Buscar y cancelar el turno original (auditoría incluida).
          2. Verificar disponibilidad en la nueva fecha/hora.
          3. Crear el nuevo turno con los mismos servicio/staff/cliente.
          4. Todo en una única transacción atómica.
        """
        # 1. Buscar turno original
        original = await self.uow.appointments.get_by_public_id(public_id)
        if not original:
            raise AppointmentNotFoundException(public_id)

        # Guardar IDs antes de cancelar
        store_id   = original.store_id
        staff_id   = original.staff_id
        service_id = original.service_id
        client_id  = original.client_id
        orig_notes = original.notes
        orig_intake_answers = original.intake_answers or {}

        # 2. Resolver servicio para calcular duración
        service = await self.uow.appointments.get_service_by_id(service_id)
        if not service:
            raise ResourceNotFoundException("Servicio", str(service_id))

        staff = await self.uow.appointments.get_staff_by_id(staff_id)
        if not staff:
            raise ResourceNotFoundException("Profesional", str(staff_id))

        ends_at = new_starts_at + timedelta(minutes=service.duration_minutes)

        # 2.5. Verificar Forcing Function: min_booking_notice_hours
        store = await self.uow.appointments.get_store_by_id(store_id)
        notice_hours = getattr(store, "min_booking_notice_hours", 2)
        now_utc = datetime.now(timezone.utc)
        if new_starts_at < now_utc + timedelta(hours=notice_hours):
            raise BookingNoticeException(notice_hours)

        # 3. Verificar bloqueos de agenda en la nueva fecha
        block = await self.uow.appointments.get_overlapping_block(staff_id, new_starts_at, ends_at)

        # 4. Bloqueo pesimista + verificar conflictos (excluyendo el turno original)
        await self.uow.appointments.lock_staff_row(staff_id)

        conflict = await self.uow.appointments.get_conflicting_appointment(
            staff_id, new_starts_at, ends_at, exclude_appointment_id=original.id
        )

        # Delegar validación al Domain Service (DDD + UX Feedback)
        try:
            self.scheduler.validate_availability(
                requested_start=new_starts_at,
                requested_end=ends_at,
                conflicting_appointment=conflict,
                overlapping_block=block
            )
        except (AppointmentConflictException, BlockedScheduleException) as e:
            search_start = conflict.ends_at if conflict else block.ends_at
            suggestion = await self._find_suggestion(staff_id, search_start, service.duration_minutes)
            
            if isinstance(e, AppointmentConflictException):
                raise AppointmentConflictException(
                    conflict_start=conflict.starts_at,
                    conflict_end=conflict.ends_at,
                    suggestion=suggestion
                )
            else:
                raise BlockedScheduleException(
                    reason=block.note,
                    block_start=block.starts_at,
                    block_end=block.ends_at,
                    suggestion=suggestion
                )

        # 5. Cancelar original (con timestamp y auditoría)
        original.apply_status_transition(AppointmentStatus.CANCELLED)
        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=original.public_id,
            actor=actor,
            payload_before={"status": "prev"},
            payload_after={
                "status": AppointmentStatus.CANCELLED.value,
                "reason": f"Reprogramado a {new_starts_at.isoformat()}",
            },
        )

        # 6. Crear nuevo turno
        new_appointment = Appointment(
            id=str(ulid.ULID()),
            store_id=store_id,
            staff_id=staff_id,
            service_id=service_id,
            client_id=client_id,
            starts_at=new_starts_at,
            ends_at=ends_at,
            duration_minutes=service.duration_minutes,
            client_name=(f"{actor.first_name or ''} {actor.last_name or ''}".strip() or actor.email),
            client_email=actor.email,
            client_phone=actor.phone,
            notes=orig_notes,
            intake_answers=orig_intake_answers,
            idempotency_key=idempotency_key,
        )
        self.uow.appointments.add(new_appointment)

        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="Appointment",
            resource_id=new_appointment.public_id,
            actor=actor,
            payload_after={
                "status": new_appointment.status,
                "starts_at": new_starts_at.isoformat(),
                "rescheduled_from": original.public_id,
            },
        )

        await self.uow.commit()

        # Invalidar caché de disponibilidad para ambos días
        for key_date in {original.starts_at.date(), new_starts_at.date()}:
            await self.redis.delete(
                f"availability:{store_id}:{service.public_id}:{key_date.isoformat()}"
            )

        return new_appointment, service, staff

    async def _find_suggestion(self, staff_id: int, start_from: datetime, duration_mins: int) -> datetime | None:
        """
        Encuentra el próximo hueco disponible (max 6 horas adelante).
        Implementa el principio de Don Norman de ofrecer salidas claras al error.
        """
        from datetime import timedelta
        current = start_from
        max_search = start_from + timedelta(hours=6)
        
        while current < max_search:
            end = current + timedelta(minutes=duration_mins)
            
            # 1. Verificar bloqueos
            block = await self.uow.appointments.get_overlapping_block(staff_id, current, end)
            if block:
                current = block.ends_at
                continue
                
            # 2. Verificar conflictos
            conflict = await self.uow.appointments.get_conflicting_appointment(staff_id, current, end)
            if conflict:
                current = conflict.ends_at
                continue
                
            # Si llegamos aquí, el hueco está libre
            return current
            
        return None

