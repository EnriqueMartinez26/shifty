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

from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import AvailabilityCacheClient, invalidate_availability
from core.database import _apply_tenant_context
from core.utils import ensure_utc_aware, now_utc
from core.uow import AbstractUnitOfWork
from core.exceptions import (
    AppException,
    AppointmentConflictException,
    AppointmentNotFoundException,
    BlockedScheduleException,
    ResourceNotFoundException,
    ValidationException,
)
from http import HTTPStatus

from modules.appointments.domain_service import SchedulingDomainService
from modules.appointments.guards import (
    reject_cancellation_while_awaiting_payment,
)
from modules.appointments.model import Appointment, AppointmentStatus
from modules.audit.model import AuditAction
from modules.auth.service import normalize_email
from modules.notifications.tasks import (
    EVENT_APPOINTMENT_BOOKED_BY_PANEL,
    EVENT_APPOINTMENT_COMPLETED,
    EVENT_APPOINTMENT_CONFIRMED,
    EVENT_APPOINTMENT_RESCHEDULED,
    is_deliverable_email,
)
from modules.payments.model import JsonValue, Payment, PaymentStatus
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from modules.public_api.repository import PublicRepository, RangeRejection
from modules.services.model import Service
from modules.staff.model import Staff, StaffBlock
from modules.users.model import User
from modules.waitlist.events import EVENT_SLOT_RELEASED, slot_released_payload

if TYPE_CHECKING:
    pass


class AppointmentBookPayload(TypedDict, total=False):
    service_id: str
    staff_id: str
    starts_at: datetime
    notes: str | None
    intake_answers: dict[str, str]
    idempotency_key: str


class ClientBookingPayload(TypedDict, total=False):
    """Alta del panel para un cliente (FF-04); ver ``AppointmentCreate``."""

    service_id: str
    staff_id: str | None
    starts_at: datetime
    notes: str | None
    idempotency_key: str
    client_name: str
    client_phone: str
    client_email: str | None
    allow_outside_schedule: bool


class AppointmentService:
    """
    Servicio principal de turnos.
    Se instancia por request, inyectando db y redis desde FastAPI Depends.
    """

    def __init__(self, uow: AbstractUnitOfWork, cache: AvailabilityCacheClient) -> None:
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
          2. Bloqueo pesimista (FOR UPDATE) antes de leer bloqueos y conflictos.
          3. Validación de agenda (con sugerencia de horario si choca).
          4. Inserción atómica + registro de auditoría + aviso en el outbox.
          5. Invalidación, fuera de la transacción.

        `actor` NO esta sujeto a min_booking_notice_hours (regla del cliente
        publico); el "no agendar en el pasado" lo garantiza AppointmentCreate.
        Reserva al propio actor como cliente: ver ``_self_booking``.
        """
        # 1. Resolver entidades acotadas a la tienda del turno: sin esto, un
        # admin podia mandar el id de un servicio o de un profesional de OTRA
        # tienda y el turno se creaba igual, apareciendo en la agenda ajena.
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

        # 2 y 3. Lock del profesional antes de leer bloqueos y conflictos.
        await self._lock_and_validate_slot(
            store_id=store_id,
            staff_id=staff.id,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=service.duration_minutes,
        )

        # 4. Creación atómica con auditoría
        appointment = _self_booking(data, store_id, service, staff, actor, ends_at)
        self.uow.appointments.add(appointment)
        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            store_id=appointment.store_id,
            actor=actor,
            payload_after={
                "status": appointment.status,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "service_id": service.public_id,
                "staff_id": staff.public_id,
            },
        )
        # El mail al cliente lo manda el lote del outbox (F2-02).
        self._publish_client_mail(appointment, EVENT_APPOINTMENT_BOOKED_BY_PANEL)
        await self._commit_before_network()
        try:
            # 5. El cupo ya no esta libre: la disponibilidad lo refleja ya.
            await invalidate_availability(self.cache, store_id, starts_at)
        finally:
            await _apply_tenant_context(self.uow.session)
        return appointment, service, staff

    async def book_for_client(
        self,
        *,
        data: ClientBookingPayload,
        store_id: str,
        actor: User,
    ) -> tuple[Appointment, Service, Staff]:
        """Turno del panel PARA UN CLIENTE de la tienda (FF-04, 2026-09-24).

        El dueno, la recepcion o el profesional cargan a alguien que llama o
        esta en el local. Decisiones del dueno (delegadas): sin antelacion
        minima (el "no mas de 5 minutos en el pasado" lo valida el schema),
        sin OTP ni campos extra, sin sena: nace CONFIRMED y sin cobro (el link
        de pago se genera despues, si hace falta, por el endpoint de siempre).
        Horario del profesional salvo ``allow_outside_schedule`` (el router lo
        reserva al admin); bloqueos, choques y buffer siempre.

        Identidad: el telefono SI adopta la ficha del cliente de ESTA tienda:
        quien carga es personal autenticado de la tienda, no un anonimo
        ("un telefono sin OTP no es de nadie" es la regla del portal). La
        ficha existente no se pisa; ``get_or_create_client`` filtra por tienda.

        Mismo camino de concurrencia que el portal (regla 4): lock del
        profesional, relectura de bloqueo y choque bajo el lock, INSERT; la
        exclusion GiST es la ultima defensa. Aviso al cliente por el outbox en
        la misma transaccion (F2-02), invalidacion despues del commit plano.
        """
        service = await self.uow.appointments.get_service_by_public_id(
            data["service_id"], store_id
        )
        if not service or not service.is_active:
            raise ResourceNotFoundException("Servicio", data["service_id"])
        starts_at = ensure_utc_aware(data["starts_at"])
        ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        outside_schedule = bool(data.get("allow_outside_schedule", False))

        repo = PublicRepository(self.uow.session)
        candidates = _requested_staff(
            await repo.qualified_staff(store_id, service), data.get("staff_id")
        )
        client = await repo.get_or_create_client(
            store_id=store_id,
            phone=data["client_phone"],
            name=data["client_name"],
            email=data.get("client_email"),
        )
        staff = await self._lock_panel_staff(
            repo,
            store_id,
            candidates,
            starts_at,
            ends_at,
            chosen=bool(data.get("staff_id")),
            require_schedule=not outside_schedule,
        )

        appointment = _client_booking(
            data, store_id, service, staff, client, starts_at, ends_at
        )
        self.uow.appointments.add(appointment)
        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            store_id=store_id,
            actor=actor,
            payload_after=_client_booking_audit(
                appointment, service, staff, outside_schedule=outside_schedule
            ),
        )
        # Un email tecnico (.noreply) o ninguno: no hay a quien avisar. Y un
        # turno que ya empezo (la tienda carga un walk-in despues) no lleva
        # "turno confirmado": el cliente ya estuvo.
        if is_deliverable_email(appointment.client_email) and starts_at >= now_utc():
            self._publish_client_mail(appointment, EVENT_APPOINTMENT_BOOKED_BY_PANEL)
        await self._commit_before_network()
        try:
            await invalidate_availability(self.cache, store_id, starts_at)
        finally:
            await _apply_tenant_context(self.uow.session)
        return appointment, service, staff

    async def _lock_panel_staff(
        self,
        repo: PublicRepository,
        store_id: str,
        candidates: list[Staff],
        starts_at: datetime,
        ends_at: datetime,
        *,
        chosen: bool,
        require_schedule: bool,
    ) -> Staff:
        """El profesional del turno, ya lockeado y con la agenda releida bajo
        el lock (regla 4). Elegido: su motivo exacto de rechazo; "cualquiera":
        el primero libre en el orden de desempate del portal."""
        buffer_minutes = await self.uow.appointments.get_store_buffer_minutes(store_id)
        if chosen:
            staff = candidates[0]
            _raise_for_rejection(
                await repo.staff_can_take_range(
                    staff.id,
                    starts_at,
                    ends_at,
                    buffer_minutes=buffer_minutes,
                    require_schedule=require_schedule,
                )
            )
            return staff
        picked = await repo.pick_staff_for_range(
            store_id,
            candidates,
            starts_at,
            ends_at,
            buffer_minutes=buffer_minutes,
            require_schedule=require_schedule,
        )
        if picked is None:
            raise AppException(
                message="No hay profesionales disponibles para ese horario",
                http_status=HTTPStatus.CONFLICT,
                error_code="NO_STAFF_AVAILABLE",
            )
        return picked

    async def _commit_before_network(self) -> None:
        """Commit PLANO antes de salir a la red (Redis) (F1-05, R8-05).

        El commit de ``TenantSession`` reaplica el contexto y con eso abre
        otra transaccion en el acto: la llamada de red corria con la conexion
        ``idle in transaction``. Patron de AUD2-B2-08: commit de
        ``AsyncSession`` (la conexion vuelve al pool), invalidacion, y recien
        despues ``_apply_tenant_context``. Desde F2-02 el mail ya no sale del
        request: va por el outbox.
        """
        await AsyncSession.commit(self.uow.session)

    def _publish_client_mail(self, appointment: Appointment, event_type: str) -> None:
        """Aviso al cliente por el outbox, en la transaccion del cambio (F2-02).

        Antes el request mandaba SMTP despues del commit (hasta 10 s por
        operacion). El lote del outbox relee el turno y manda tras su commit;
        si este commit no ocurre, el aviso tampoco existe.
        """
        self.uow.outbox.publish(
            store_id=appointment.store_id,
            event_type=event_type,
            payload={"appointment_id": appointment.id},
        )

    async def _lock_and_validate_slot(
        self,
        *,
        store_id: str,
        staff_id: str,
        starts_at: datetime,
        ends_at: datetime,
        duration_minutes: int,
        exclude_appointment_id: str | None = None,
    ) -> None:
        """Lock del profesional, relectura de bloqueo y choque, y validacion.

        Regla 4: el ``FOR UPDATE`` va ANTES de leer bloqueos y conflictos. Antes
        los bloqueos se leian sin el lock: un bloqueo creado entre esa lectura
        y el INSERT dejaba un turno adentro (2026-09-10; en la reprogramacion,
        B1-05). Lo comparten ``book`` y ``reschedule``.
        """
        buffer_minutes = await self.uow.appointments.get_store_buffer_minutes(store_id)
        block, conflict = await self.uow.appointments.lock_and_read_range(
            staff_id,
            starts_at,
            ends_at,
            buffer_minutes=buffer_minutes,
            exclude_appointment_id=exclude_appointment_id,
        )
        await self._validate_or_suggest(
            store_id=store_id,
            staff_id=staff_id,
            requested_start=starts_at,
            requested_end=ends_at,
            conflict=conflict,
            block=block,
            duration_minutes=duration_minutes,
            buffer_minutes=buffer_minutes,
        )

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
            store_id=appointment.store_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status},
        )
        self._publish_slot_released(appointment, reason="cancelled")

        await self.uow.commit()

        await invalidate_availability(
            self.cache, appointment.store_id, appointment.starts_at
        )

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
            store_id=appointment.store_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status},
        )

        # Mail "turno confirmado": por el outbox (F2-02), best-effort; un SMTP
        # caido no deshace la confirmacion.
        self._publish_client_mail(appointment, EVENT_APPOINTMENT_CONFIRMED)
        await self.uow.commit()
        return appointment

    def _publish_slot_released(self, appointment: Appointment, *, reason: str) -> None:
        """Lista de espera: el cupo vuelve a estar libre (misma transaccion)."""
        self.uow.outbox.publish(
            store_id=appointment.store_id,
            event_type=EVENT_SLOT_RELEASED,
            payload=slot_released_payload(
                staff_id=appointment.staff_id,
                service_id=appointment.service_id,
                appointment_id=appointment.id,
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                reason=reason,
            ),
        )

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
            store_id=appointment.store_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={
                "status": appointment.status,
                "completed_at": appointment.completed_at.isoformat()
                if appointment.completed_at
                else None,
            },
        )

        # Mail "reserva tu proximo turno": por el outbox (F2-02), que respeta
        # el interruptor de mails automaticos de la tienda.
        self._publish_client_mail(appointment, EVENT_APPOINTMENT_COMPLETED)
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
            store_id=appointment.store_id,
            actor=actor,
            payload_before=payload_before,
            payload_after={"status": appointment.status},
        )

        await self.uow.commit()
        return appointment

    async def release_pending(self, *, public_id: str, actor: User) -> Appointment:
        """Libera un turno pendiente y vence su pago en curso.

        Cruza dos agregados (turno + pago); por eso es un caso de uso de
        servicio y no del router. Un turno con pago ya acreditado no se libera:
        primero hay que reembolsar.

        El link de Mercado Pago NO se vence aca (B1-04, regla 5): antes el PUT
        a MP corria con el turno y el pago bajo ``FOR UPDATE`` y, con MP caido,
        el turno no se liberaba (502 ``PAYMENT_PREFERENCE_EXPIRATION_FAILED``).
        Ahora se publica ``payment.preference.expire`` en la misma transaccion
        y el outbox lo vence despues, sin lock, con reintento.
        """
        appointment = await self._lock_releasable(public_id, actor)
        payment = await self._expire_pending_payment(appointment, actor)

        previous_status = appointment.status
        appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            store_id=appointment.store_id,
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
        self._publish_slot_released(appointment, reason="released")
        await self.uow.commit()

        await invalidate_availability(
            self.cache, appointment.store_id, appointment.starts_at
        )
        return appointment

    async def _lock_releasable(self, public_id: str, actor: User) -> Appointment:
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
        return appointment

    async def _expire_pending_payment(
        self, appointment: Appointment, actor: User
    ) -> Payment | None:
        """Vence el cobro pendiente bajo lock; el link de MP va por el outbox."""
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
                # Se vence despues del commit, desde el outbox (B1-04).
                self.uow.outbox.publish(
                    store_id=actor.store_id,
                    event_type=EVENT_PREFERENCE_EXPIRE,
                    payload={
                        "appointment_id": appointment.id,
                        "payment_id": payment.id,
                        "preference_id": payment.preference_id,
                    },
                )
            payment.apply_status(
                PaymentStatus.EXPIRED.value,
                payload={
                    "reason": "manual_store_release",
                    "released_by": actor.public_id,
                },
            )
        return payment

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
            store_id=appointment.store_id,
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
          1. Lock y lectura del turno original (guarda de cobro pendiente).
          2. Lock del profesional y validación de la nueva fecha/hora.
          3. Cancelar el original y crear el nuevo, con auditoría.
          4. Todo en una única transacción atómica, con el aviso en el outbox;
             invalidación después.

        El dueno reprograma sin la antelacion minima; el "no pasado" lo valida
        el schema AppointmentReschedule.
        """
        await self.uow.appointments.lock_by_public_id(public_id, actor.store_id)
        original = await self.uow.appointments.get_by_public_id(
            public_id, actor.store_id
        )
        if not original:
            raise AppointmentNotFoundException(public_id)
        # Reprogramar cancela el turno original: le corresponde el mismo guard
        # que a cancel(). Sin esto la preferencia de pago quedaba viva.
        reject_cancellation_while_awaiting_payment(original)

        service = await self.uow.appointments.get_service_by_id(
            original.service_id, actor.store_id
        )
        if not service:
            raise ResourceNotFoundException("Servicio", str(original.service_id))
        staff = await self.uow.appointments.get_staff_by_id(
            original.staff_id, actor.store_id
        )
        if not staff:
            raise ResourceNotFoundException("Profesional", str(original.staff_id))

        ends_at = new_starts_at + timedelta(minutes=service.duration_minutes)
        await self._lock_and_validate_slot(
            store_id=original.store_id,
            staff_id=original.staff_id,
            starts_at=new_starts_at,
            ends_at=ends_at,
            duration_minutes=service.duration_minutes,
            exclude_appointment_id=original.id,
        )

        new_appointment = await self._swap_for_new_slot(
            original, service, new_starts_at, ends_at, idempotency_key, actor
        )
        # El cliente tiene que enterarse del horario nuevo: la fila nueva nace
        # despues de starts_at-24h, asi que el recordatorio de 24 horas ya no
        # le corresponde y sin este mail no se enteraba por ningun canal. Va
        # por el outbox, en esta transaccion (F2-02).
        self._publish_client_mail(new_appointment, EVENT_APPOINTMENT_RESCHEDULED)
        await self._commit_before_network()
        try:
            await invalidate_availability(
                self.cache, original.store_id, original.starts_at, new_starts_at
            )
        finally:
            await _apply_tenant_context(self.uow.session)
        return new_appointment, service, staff

    async def _swap_for_new_slot(
        self,
        original: Appointment,
        service: Service,
        new_starts_at: datetime,
        ends_at: datetime,
        idempotency_key: str,
        actor: User,
    ) -> Appointment:
        """Cancela el original y agrega el nuevo, con auditoria. Sin commit."""
        # El turno nuevo se arma ANTES de cancelar: copia del original el
        # contacto DEL CLIENTE (no el de quien reprograma: se copiaba el del
        # administrador y la confirmacion, el recordatorio y el WhatsApp
        # apuntaban a la tienda misma) y el precio congelado (reprogramar
        # cambia el horario, no re-tarifa al precio de lista de hoy).
        # El estado se lee ANTES de cancelar el original: la copia lo conserva
        # y ``apply_status_transition`` ya lo habria pisado.
        estado_previo = original.status
        new_appointment = _rescheduled_copy(
            original, service, new_starts_at, ends_at, idempotency_key, estado_previo
        )
        original.apply_status_transition(AppointmentStatus.CANCELLED)
        self._publish_slot_released(original, reason="rescheduled")
        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=original.public_id,
            store_id=original.store_id,
            actor=actor,
            payload_before={"status": "prev"},
            payload_after={
                "status": AppointmentStatus.CANCELLED.value,
                "reason": f"Reprogramado a {new_starts_at.isoformat()}",
            },
        )
        self.uow.appointments.add(new_appointment)
        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="Appointment",
            resource_id=new_appointment.public_id,
            store_id=new_appointment.store_id,
            actor=actor,
            payload_after={
                "status": new_appointment.status,
                "starts_at": new_starts_at.isoformat(),
                "rescheduled_from": original.public_id,
            },
        )
        return new_appointment

    async def _validate_or_suggest(
        self,
        *,
        store_id: str,
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
                store_id, staff_id, search_start, duration_minutes, buffer_minutes
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
        store_id: str,
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

        Bloqueos y turnos de toda la ventana se traen en UNA consulta cada uno
        y se recorren en memoria (regla 12, B1-15): antes eran dos consultas
        por intento, hasta 48, con el lock del profesional tomado. Mismo
        criterio que antes: primero bloqueos, despues choques ensanchados por
        el buffer, en orden de inicio.
        """
        duration = timedelta(minutes=duration_mins)
        buffer = timedelta(minutes=buffer_minutes)
        current = ensure_utc_aware(start_from)
        max_search = current + timedelta(hours=6)

        # La ventana cubre todo intento posible: [current, max_search + duracion),
        # y para los turnos ensanchada por el buffer a cada lado.
        blocks = [
            (ensure_utc_aware(block.starts_at), ensure_utc_aware(block.ends_at))
            for block in await self.uow.appointments.list_active_blocks_in_window(
                staff_id, current, max_search + duration, store_id=store_id
            )
        ]
        booked = [
            (ensure_utc_aware(appt.starts_at), ensure_utc_aware(appt.ends_at))
            for appt in await self.uow.appointments.list_active_appointments_in_window(
                staff_id,
                current - buffer,
                max_search + duration + buffer,
                store_id=store_id,
            )
        ]

        while current < max_search:
            end = current + duration

            # 1. Verificar bloqueos
            block_end = next(
                (
                    b_end
                    for b_start, b_end in blocks
                    if b_start < end and b_end > current
                ),
                None,
            )
            if block_end is not None:
                current = block_end
                continue

            # 2. Verificar conflictos
            conflict_end = next(
                (
                    a_end
                    for a_start, a_end in booked
                    if a_start < end + buffer and a_end > current - buffer
                ),
                None,
            )
            if conflict_end is not None:
                # Saltar hasta despues del turno MAS el buffer: si solo saltaramos
                # a ends_at, con buffer > 0 el mismo turno seguiria en conflicto
                # (se extiende 'buffer' mas alla) y current no avanzaria -> loop
                # infinito.
                current = conflict_end + buffer
                continue

            # Si llegamos aquí, el hueco está libre
            return current

        return None


def _self_booking(
    data: AppointmentBookPayload,
    store_id: str,
    service: Service,
    staff: Staff,
    actor: User,
    ends_at: datetime,
) -> Appointment:
    """Turno del panel a nombre del propio actor (client_id=actor.id).

    Es un auto-booking, no un alta para un tercero. Cargar un walk-in (un
    cliente distinto al staff logueado) es responsabilidad del alta publica
    (``PublicBookingService.book``), que acepta client_name/phone/email y es
    lo que usa el boton "Nuevo turno" del panel admin.
    """
    return Appointment(
        id=str(ulid.ULID()),
        store_id=store_id,
        staff_id=staff.id,
        service_id=service.id,
        client_id=actor.id,
        starts_at=data["starts_at"],
        ends_at=ends_at,
        duration_minutes=service.duration_minutes,
        # Congelamos el precio de lista del momento: el reporte de ingresos y
        # el cobro manual usan este valor, no el precio actual del servicio.
        price_amount=Decimal(str(service.price or 0)),
        client_name=(
            f"{actor.first_name or ''} {actor.last_name or ''}".strip() or actor.email
        ),
        client_email=actor.email,
        client_phone=actor.phone,
        notes=data.get("notes"),
        intake_answers=data.get("intake_answers") or {},
        idempotency_key=data.get("idempotency_key"),
    )


def _requested_staff(
    qualified: list[Staff], staff_public_id: str | None
) -> list[Staff]:
    """Candidatos del alta: el elegido (422 si no hace el servicio o no es de
    la tienda) o todos los que lo hacen."""
    if not staff_public_id:
        return qualified
    elegido = [m for m in qualified if m.public_id == staff_public_id]
    if not elegido:
        raise ValidationException("El profesional no realiza el servicio seleccionado")
    return elegido


def _client_booking_audit(
    appointment: Appointment, service: Service, staff: Staff, *, outside_schedule: bool
) -> dict[str, JsonValue]:
    """Lo que la auditoria guarda del alta del panel para un cliente."""
    return {
        "status": appointment.status,
        "starts_at": appointment.starts_at.isoformat(),
        "ends_at": appointment.ends_at.isoformat(),
        "service_id": service.public_id,
        "staff_id": staff.public_id,
        "source": "panel_for_client",
        "outside_schedule": outside_schedule,
    }


def _raise_for_rejection(rejection: RangeRejection | None) -> None:
    """Mismos codigos que la reprogramacion del cliente (``_check_new_slot``)."""
    if rejection is RangeRejection.OUT_OF_SCHEDULE:
        raise AppException(
            message="El profesional no atiende en ese horario",
            http_status=HTTPStatus.CONFLICT,
            error_code="OUT_OF_SCHEDULE",
        )
    if rejection is RangeRejection.BLOCKED:
        raise AppException(
            message="Ese horario esta bloqueado en la agenda",
            http_status=HTTPStatus.CONFLICT,
            error_code="SCHEDULE_BLOCKED",
        )
    if rejection is RangeRejection.TAKEN:
        raise AppointmentConflictException()


def _client_booking(
    data: ClientBookingPayload,
    store_id: str,
    service: Service,
    staff: Staff,
    client: User,
    starts_at: datetime,
    ends_at: datetime,
) -> Appointment:
    """Turno del panel para un cliente (FF-04): confirmado, sin retencion."""
    email = data.get("client_email")
    return Appointment(
        id=str(ulid.ULID()),
        store_id=store_id,
        staff_id=staff.id,
        service_id=service.id,
        client_id=client.id,
        starts_at=starts_at,
        ends_at=ends_at,
        duration_minutes=service.duration_minutes,
        # Precio de lista congelado, como el resto de las altas del panel.
        price_amount=Decimal(str(service.price or 0)),
        # Snapshot de ESTA reserva (mismo criterio que el portal): el nombre de
        # la ficha, y el email que dejaron ahora sin pisar el de la ficha.
        client_name=client.full_name or data["client_name"],
        client_email=normalize_email(email) if email else client.email,
        client_phone=client.phone,
        notes=data.get("notes"),
        intake_answers={},
        idempotency_key=data["idempotency_key"],
        # Sin sena: nace confirmado y sin ``expires_at`` (no hay retencion que
        # vencer; el job de expiracion no lo toca).
        status=AppointmentStatus.CONFIRMED.value,
        expires_at=None,
        # El personal no es el cliente dando su consentimiento: el alta del
        # panel no pide ``accepts_terms`` y no inventa uno (PV-09 es del portal).
        terms_accepted_at=None,
    )


def _rescheduled_copy(
    original: Appointment,
    service: Service,
    new_starts_at: datetime,
    ends_at: datetime,
    idempotency_key: str,
    estado_previo: str,
) -> Appointment:
    # Mismo criterio que el portal (``public_api.service._rescheduled_copy``,
    # AUD2-B1-14; al panel en AUD2-POST-05, 2026-09-23): el turno movido
    # conserva el estado del original. Antes nacia con el default de la
    # columna y un confirmado volvia a "pendiente de confirmar" sin aviso. A
    # esta altura no hay sena de por medio (``pending_payment`` lo frena
    # ``reject_cancellation_while_awaiting_payment``), asi que lo que se
    # conserva es un ``confirmed`` sin retencion que vencer. Un pendiente
    # conserva la retencion que TENIA: la del portal (hasta el inicio) pasa
    # al horario nuevo; el alta del panel no retiene y moverlo tampoco.
    confirmado = estado_previo == AppointmentStatus.CONFIRMED.value
    retenido = not confirmado and original.expires_at is not None
    return Appointment(
        status=(
            AppointmentStatus.CONFIRMED.value
            if confirmado
            else AppointmentStatus.PENDING.value
        ),
        expires_at=new_starts_at if retenido else None,
        id=str(ulid.ULID()),
        store_id=original.store_id,
        staff_id=original.staff_id,
        service_id=original.service_id,
        client_id=original.client_id,
        starts_at=new_starts_at,
        ends_at=ends_at,
        duration_minutes=service.duration_minutes,
        price_amount=(
            original.price_amount
            if original.price_amount is not None
            else Decimal(str(service.price or 0))
        ),
        client_name=original.client_name,
        client_email=original.client_email,
        client_phone=original.client_phone,
        notes=original.notes,
        intake_answers=original.intake_answers or {},
        idempotency_key=idempotency_key,
    )
