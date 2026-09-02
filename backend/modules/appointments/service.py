"""
Capa de Servicios de Turnos (AppointmentService).

Responsabilidades:
- Orquestación de la lógica de negocio (crear, cancelar, confirmar, completar).
- Coordinación entre repositorios, auditoría y notificaciones.
- Los repositorios son solo "colecciones de datos"; la inteligencia está aquí.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

import ulid

from core.cache import CacheInvalidator
from core.circuit_breaker import CircuitBreakerOpenError
from core.uow import AbstractUnitOfWork
from core.exceptions import (
    AppException,
    AppointmentConflictException,
    AppointmentNotFoundException,
    BlockedScheduleException,
    ResourceNotFoundException,
)
from http import HTTPStatus

from modules.appointments.domain_service import SchedulingDomainService
from modules.appointments.guards import (
    reject_cancellation_while_awaiting_payment,
)
from modules.appointments.model import Appointment, AppointmentStatus
from modules.audit.model import AuditAction
from modules.notifications.tasks import enqueue_confirmation_email
from modules.payments.model import PaymentStatus
from modules.payments.service import expire_mercadopago_preference
from modules.services.model import Service
from modules.staff.model import Staff, StaffBlock
from modules.users.model import User

if TYPE_CHECKING:
    pass


class AppointmentBookPayload(TypedDict, total=False):
    service_id: str
    staff_id: str
    starts_at: datetime
    notes: str | None
    intake_answers: dict[str, str]
    idempotency_key: str


class AppointmentService:
    """
    Servicio principal de turnos.
    Se instancia por request, inyectando db y redis desde FastAPI Depends.
    """

    def __init__(self, uow: AbstractUnitOfWork, cache: CacheInvalidator) -> None:
        self.uow = uow
        self.cache = cache
        self.scheduler = SchedulingDomainService()

    # ------------------------------------------------------------------
    # Crear turno
    # ------------------------------------------------------------------

    async def book(
        self,
        *,
        data: AppointmentBookPayload,
        store_id: str,
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
        #
        # Se resuelven acotadas a la tienda del turno: sin esto, un admin podia
        # mandar el id de un servicio o de un profesional de OTRA tienda y el
        # turno se creaba igual, apareciendo en la agenda ajena.
        service = await self.uow.appointments.get_service_by_public_id(
            data["service_id"], store_id
        )
        if not service:
            raise ResourceNotFoundException("Servicio", data["service_id"])

        staff = await self.uow.appointments.get_staff_by_public_id(
            data["staff_id"], store_id
        )
        if not staff:
            raise ResourceNotFoundException("Profesional", data["staff_id"])

        starts_at: datetime = data["starts_at"]
        ends_at: datetime = starts_at + timedelta(minutes=service.duration_minutes)

        # Nota: el dueno NO esta sujeto a min_booking_notice_hours (esa regla
        # es para el cliente). Puede cargar un walk-in del momento. El "no
        # agendar en el pasado" lo garantiza el schema AppointmentCreate.

        # 2. Verificar bloqueos de agenda --------------------------------
        block = await self.uow.appointments.get_overlapping_block(
            staff.id, starts_at, ends_at
        )

        # 3. Bloqueo pesimista + verificación de conflictos --------------
        await self.uow.appointments.lock_staff_row(staff.id)
        buffer_minutes = await self.uow.appointments.get_store_buffer_minutes(store_id)
        conflict = await self.uow.appointments.get_conflicting_appointment(
            staff.id, starts_at, ends_at, buffer_minutes=buffer_minutes
        )

        # Delegar validación al Domain Service (DDD + UX Feedback)
        await self._validate_or_suggest(
            staff_id=staff.id,
            requested_start=starts_at,
            requested_end=ends_at,
            conflict=conflict,
            block=block,
            duration_minutes=service.duration_minutes,
            buffer_minutes=buffer_minutes,
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
            # Congelamos el precio de lista del momento: el reporte de ingresos y
            # el cobro manual usan este valor, no el precio actual del servicio.
            price_amount=Decimal(str(service.price or 0)),
            client_name=(
                f"{actor.first_name or ''} {actor.last_name or ''}".strip()
                or actor.email
            ),
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
        await enqueue_confirmation_email(
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
        await self.cache.delete(cache_key)

        return appointment, service, staff

    # ------------------------------------------------------------------
    # Cambios de estado
    # ------------------------------------------------------------------

    async def cancel(self, *, public_id: str, actor: User) -> Appointment:
        """Cancela un turno verificando la transición de estado."""
        # Lock pesimista antes de leer: sin esto, dos transiciones validas
        # y distintas pueden partir del mismo estado origen (TOCTOU).
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        appointment = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
        if not appointment:
            raise AppointmentNotFoundException(public_id)
        reject_cancellation_while_awaiting_payment(appointment)

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
        await self.cache.delete(cache_key)

        return appointment

    async def confirm(self, *, public_id: str, actor: User) -> Appointment:
        """Confirma un turno (solo ADMIN o STAFF)."""
        # Lock pesimista antes de leer: sin esto, dos transiciones validas
        # y distintas pueden partir del mismo estado origen (TOCTOU).
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        appointment = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
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
        # Lock pesimista antes de leer: sin esto, dos transiciones validas
        # y distintas pueden partir del mismo estado origen (TOCTOU).
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        appointment = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
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
            payload_after={
                "status": appointment.status,
                "completed_at": appointment.completed_at.isoformat()
                if appointment.completed_at
                else None,
            },
        )

        await self.uow.commit()
        return appointment

    async def mark_absent(self, *, public_id: str, actor: User) -> Appointment:
        """
        Marca el turno como AUSENTE (cliente no se presentó).
        Solo aplicable desde CONFIRMED.
        """
        # Lock pesimista antes de leer: sin esto, dos transiciones validas
        # y distintas pueden partir del mismo estado origen (TOCTOU).
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        appointment = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
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

    async def release_pending(self, *, public_id: str, actor: User) -> Appointment:
        """Libera un turno pendiente y vence su pago en curso.

        Cruza dos agregados (turno + pago) y toca el gateway de Mercado Pago;
        por eso es un caso de uso de servicio y no del router. Un turno con pago
        ya acreditado no se libera: primero hay que reembolsar.
        """
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        appointment = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
        if not appointment:
            raise AppointmentNotFoundException(public_id)
        if appointment.status not in {
            AppointmentStatus.PENDING.value,
            AppointmentStatus.PENDING_PAYMENT.value,
        }:
            raise AppException(
                message="Solo se pueden liberar turnos pendientes",
                http_status=HTTPStatus.CONFLICT,
                error_code="APPOINTMENT_NOT_RELEASABLE",
            )

        payment = await self.uow.payments.get_by_appointment_locked(
            appointment.id, actor.store_id
        )
        if payment and (
            payment.is_accredited or payment.status == PaymentStatus.REFUNDED.value
        ):
            raise AppException(
                message="No se puede liberar un turno que ya tiene un pago acreditado",
                http_status=HTTPStatus.CONFLICT,
                error_code="PAID_APPOINTMENT_NOT_RELEASABLE",
            )
        if payment and payment.status == PaymentStatus.PENDING.value:
            if payment.preference_id:
                try:
                    await expire_mercadopago_preference(
                        self.uow.session,
                        store_id=actor.store_id,
                        preference_id=payment.preference_id,
                    )
                except (RuntimeError, CircuitBreakerOpenError) as exc:
                    raise AppException(
                        message=(
                            "No se libero el turno porque Mercado Pago no pudo "
                            "vencer el enlace de pago"
                        ),
                        http_status=HTTPStatus.BAD_GATEWAY,
                        error_code="PAYMENT_PREFERENCE_EXPIRATION_FAILED",
                    ) from exc
            payment.apply_status(
                PaymentStatus.EXPIRED.value,
                payload={
                    "reason": "manual_store_release",
                    "released_by": actor.public_id,
                },
            )

        previous_status = appointment.status
        appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=actor,
            payload_before={"status": previous_status},
            payload_after={
                "status": appointment.status,
                "reason": "manual_store_release",
            },
        )
        self.uow.outbox.publish(
            store_id=actor.store_id,
            event_type="appointment.released",
            payload={
                "appointment_id": appointment.id,
                "payment_id": payment.id if payment else None,
                "released_by": actor.public_id,
            },
        )
        await self.uow.commit()

        cache_key = (
            f"availability:{appointment.store_id}:*:"
            f"{appointment.starts_at.date().isoformat()}"
        )
        await self.cache.delete(cache_key)
        return appointment

    async def update_staff_notes(
        self, *, public_id: str, notes_staff: str, actor: User
    ) -> Appointment:
        """
        Actualiza las notas del profesional sobre el turno.
        Solo STAFF o ADMIN pueden editar estas notas.
        """
        appointment = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
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
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        original = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
        if not original:
            raise AppointmentNotFoundException(public_id)
        # Reprogramar cancela el turno original: le corresponde el mismo guard
        # que a cancel(). Sin esto la preferencia de pago quedaba viva.
        reject_cancellation_while_awaiting_payment(original)

        # Guardar IDs antes de cancelar
        store_id = original.store_id
        staff_id = original.staff_id
        service_id = original.service_id
        client_id = original.client_id
        orig_notes = original.notes
        orig_intake_answers = original.intake_answers or {}
        # El precio quedo congelado en la reserva original: reprogramar cambia
        # el horario, no re-tarifa al precio de lista de hoy.
        orig_price_amount = original.price_amount

        # 2. Resolver servicio para calcular duración
        service = await self.uow.appointments.get_service_by_id(
            service_id, actor.store_id
        )
        if not service:
            raise ResourceNotFoundException("Servicio", str(service_id))

        staff = await self.uow.appointments.get_staff_by_id(staff_id, actor.store_id)
        if not staff:
            raise ResourceNotFoundException("Profesional", str(staff_id))

        ends_at = new_starts_at + timedelta(minutes=service.duration_minutes)

        # El dueno reprograma sin la antelacion minima; el "no pasado" lo
        # valida el schema AppointmentReschedule.

        # 3. Verificar bloqueos de agenda en la nueva fecha
        block = await self.uow.appointments.get_overlapping_block(
            staff_id, new_starts_at, ends_at
        )

        # 4. Bloqueo pesimista + verificar conflictos (excluyendo el turno original)
        await self.uow.appointments.lock_staff_row(staff_id)

        buffer_minutes = await self.uow.appointments.get_store_buffer_minutes(store_id)
        conflict = await self.uow.appointments.get_conflicting_appointment(
            staff_id,
            new_starts_at,
            ends_at,
            exclude_appointment_id=original.id,
            buffer_minutes=buffer_minutes,
        )

        # Delegar validación al Domain Service (DDD + UX Feedback)
        await self._validate_or_suggest(
            staff_id=staff_id,
            requested_start=new_starts_at,
            requested_end=ends_at,
            conflict=conflict,
            block=block,
            duration_minutes=service.duration_minutes,
            buffer_minutes=buffer_minutes,
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
            price_amount=(
                orig_price_amount
                if orig_price_amount is not None
                else Decimal(str(service.price or 0))
            ),
            client_name=(
                f"{actor.first_name or ''} {actor.last_name or ''}".strip()
                or actor.email
            ),
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
            await self.cache.delete(
                f"availability:{store_id}:{service.public_id}:{key_date.isoformat()}"
            )

        return new_appointment, service, staff

    async def _validate_or_suggest(
        self,
        *,
        staff_id: str,
        requested_start: datetime,
        requested_end: datetime,
        conflict: Appointment | None,
        block: StaffBlock | None,
        duration_minutes: int,
        buffer_minutes: int,
    ) -> None:
        """Valida disponibilidad y, si choca, re-lanza con una sugerencia de
        horario (Don Norman: ofrecer una salida al error). Lo comparten ``book``
        y ``reschedule``, que antes duplicaban este bloque casi textual."""
        try:
            self.scheduler.validate_availability(
                requested_start=requested_start,
                requested_end=requested_end,
                conflicting_appointment=conflict,
                overlapping_block=block,
            )
        except (AppointmentConflictException, BlockedScheduleException) as e:
            assert conflict is not None or block is not None
            if conflict is not None:
                search_start = conflict.ends_at
            else:
                assert block is not None
                search_start = block.ends_at
            suggestion = await self._find_suggestion(
                staff_id, search_start, duration_minutes, buffer_minutes
            )
            if isinstance(e, AppointmentConflictException):
                assert conflict is not None
                raise AppointmentConflictException(
                    conflict_start=conflict.starts_at,
                    conflict_end=conflict.ends_at,
                    suggestion=suggestion,
                )
            assert block is not None
            raise BlockedScheduleException(
                reason=block.note,
                block_start=block.starts_at,
                block_end=block.ends_at,
                suggestion=suggestion,
            )

    async def _find_suggestion(
        self,
        staff_id: str,
        start_from: datetime,
        duration_mins: int,
        buffer_minutes: int = 0,
    ) -> datetime | None:
        """
        Encuentra el próximo hueco disponible (max 6 horas adelante).
        Implementa el principio de Don Norman de ofrecer salidas claras al error.

        Respeta el mismo ``buffer_minutes`` que la validación de conflictos, para
        no sugerir un horario que después el alta rechazaría.
        """
        from datetime import timedelta

        current = start_from
        max_search = start_from + timedelta(hours=6)

        while current < max_search:
            end = current + timedelta(minutes=duration_mins)

            # 1. Verificar bloqueos
            block = await self.uow.appointments.get_overlapping_block(
                staff_id, current, end
            )
            if block:
                current = block.ends_at
                continue

            # 2. Verificar conflictos
            conflict = await self.uow.appointments.get_conflicting_appointment(
                staff_id, current, end, buffer_minutes=buffer_minutes
            )
            if conflict:
                # Saltar hasta despues del turno MAS el buffer: si solo saltaramos
                # a ends_at, con buffer > 0 el mismo turno seguiria en conflicto
                # (se extiende 'buffer' mas alla) y current no avanzaria -> loop
                # infinito.
                current = conflict.ends_at + timedelta(minutes=buffer_minutes)
                continue

            # Si llegamos aquí, el hueco está libre
            return current

        return None
