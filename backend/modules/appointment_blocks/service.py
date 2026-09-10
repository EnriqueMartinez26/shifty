"""Bloqueos de agenda: dueno de la transaccion y de los turnos afectados.

Hasta el 2026-09-10 el router creaba bloqueos sin mirar los turnos ya
reservados: quedaban activos adentro del bloqueo (huerfanos), el recordatorio
les seguia saliendo y el cliente llegaba a un profesional que no atendia. Y
``book`` leia los bloqueos antes de tomar el lock del profesional, asi que un
turno podia colarse dentro de un bloqueo recien creado.

Ahora:
- ``preview`` lista los turnos activos que caen en los rangos, clasificados
  (cancelable, esperando pago, con sena acreditada) para que el dueno decida.
- ``create_blocks`` toma el lock de cada profesional, vuelve a listar
  afectados bajo lock y, si hay, exige ``cancel_affected`` (solo administradores):
  cancela los cancelables con auditoria y aviso al cliente por outbox, y deja
  listados los que requieren decision humana (pago pendiente en Mercado Pago,
  sena acreditada). Nunca llama a Mercado Pago bajo el lock.
- Los commits viven aca, no en el router (patron de ``appointments``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from core.availability_cache import (
    AvailabilityCacheClient,
    invalidate_availability_range,
)
from core.exceptions import (
    AppException,
    PermissionDeniedException,
    ResourceNotFoundException,
    StaffNotFoundException,
    ValidationException,
)
from core.roles import STORE_MANAGERS, has_any_role
from core.uow import AbstractUnitOfWork
from modules.appointments.model import Appointment, AppointmentStatus
from modules.audit.model import AuditAction
from modules.notifications.tasks import build_client_details, is_deliverable_email
from modules.staff.model import Staff, StaffBlock
from modules.stores.model import Store
from modules.users.model import User

EVENT_CANCELLED_BY_BLOCK = "appointment.cancelled_by_block"

Range = tuple[datetime, datetime]


def expand_ranges(
    starts_at: datetime,
    ends_at: datetime,
    recurrence: str,
    recurrence_until: datetime | None,
    max_occurrences: int,
) -> list[Range]:
    """Rangos de un bloqueo simple o recurrente (funcion pura, testeable)."""
    ranges: list[Range] = [(starts_at, ends_at)]
    if recurrence == "none":
        return ranges
    step = timedelta(days=1) if recurrence == "daily" else timedelta(days=7)
    current_start, current_end = starts_at, ends_at
    while len(ranges) < max_occurrences:
        current_start += step
        current_end += step
        if recurrence_until and current_start > recurrence_until:
            break
        ranges.append((current_start, current_end))
    return ranges


@dataclass
class AffectedAppointment:
    appointment: Appointment
    reason: str | None  # None = cancelable; si no, por que requiere decision humana

    @property
    def cancellable(self) -> bool:
        return self.reason is None


@dataclass
class BlockCreationResult:
    blocks: list[StaffBlock]
    cancelled: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


class AppointmentBlockService:
    def __init__(
        self, uow: AbstractUnitOfWork, cache: AvailabilityCacheClient, actor: User
    ) -> None:
        self.uow = uow
        self.cache = cache
        self.actor = actor

    # ------------------------------------------------------------- lectura
    async def _staff_for(self, staff_id: str | None) -> list[Staff]:
        stmt = select(Staff).where(
            Staff.store_id == self.actor.store_id, Staff.is_active.is_(True)
        )
        if staff_id:
            stmt = stmt.where(Staff.id == staff_id)
        result = await self.uow.session.execute(stmt)
        members = list(result.scalars().all())
        if staff_id and not members:
            raise StaffNotFoundException(identifier=staff_id)
        if not members:
            raise ValidationException(
                "No hay personal activo para bloquear. Cargá al menos un profesional."
            )
        return members

    async def _classify(
        self, appointments: list[Appointment]
    ) -> list[AffectedAppointment]:
        affected: list[AffectedAppointment] = []
        for appointment in appointments:
            if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
                affected.append(AffectedAppointment(appointment, "pending_payment"))
                continue
            payment = await self.uow.payments.get_by_appointment(
                appointment.id, self.actor.store_id
            )
            if payment is not None and payment.is_accredited:
                affected.append(AffectedAppointment(appointment, "has_deposit"))
                continue
            affected.append(AffectedAppointment(appointment, None))
        return affected

    async def preview(
        self, *, staff_id: str | None, ranges: list[Range]
    ) -> list[AffectedAppointment]:
        members = await self._staff_for(staff_id)
        appointments = await self.uow.appointments.list_active_overlapping(
            self.actor.store_id, [m.id for m in members], ranges
        )
        return await self._classify(appointments)

    # ------------------------------------------------------------- escritura
    async def create_blocks(
        self,
        *,
        staff_id: str | None,
        ranges: list[Range],
        reason: str,
        cancel_affected: bool,
    ) -> BlockCreationResult:
        members = await self._staff_for(staff_id)
        staff_ids = [m.id for m in members]
        for member_id in staff_ids:
            await self.uow.appointments.lock_staff_row(member_id)

        appointments = await self.uow.appointments.list_active_overlapping(
            self.actor.store_id, staff_ids, ranges, lock=True
        )
        affected = await self._classify(appointments)
        result = BlockCreationResult(blocks=[])

        if affected and not cancel_affected:
            raise AppException(
                message=(
                    f"Hay {len(affected)} turno(s) reservado(s) dentro del bloqueo. "
                    "Revisalos y confirmá la cancelación."
                ),
                http_status=409,
                error_code="BLOCK_HAS_APPOINTMENTS",
                detail={"affected": len(affected)},
            )
        if affected and cancel_affected:
            if not has_any_role(self.actor, STORE_MANAGERS):
                raise PermissionDeniedException(
                    action="Solo un administrador puede cancelar turnos en bloque"
                )
            store = await self.uow.session.get(Store, self.actor.store_id)
            for item in affected:
                if not item.cancellable:
                    result.skipped.append(
                        (item.appointment.public_id, item.reason or "")
                    )
                    continue
                await self._cancel_for_block(item.appointment, reason, store)
                result.cancelled.append(item.appointment.public_id)

        for member_id in staff_ids:
            for starts_at, ends_at in ranges:
                block = StaffBlock(
                    store_id=self.actor.store_id,
                    staff_id=member_id,
                    start_time=starts_at,
                    end_time=ends_at,
                    reason=reason,
                )
                self.uow.session.add(block)
                result.blocks.append(block)
        # Los ids se generan en el flush; la auditoria los necesita.
        await self.uow.session.flush()

        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="AppointmentBlock",
            resource_id=result.blocks[0].id if result.blocks else "",
            actor=self.actor,
            payload_after={
                "reason": reason,
                "ranges": len(ranges),
                "staff": len(staff_ids),
                "cancelled": result.cancelled,
                "skipped": [pid for pid, _ in result.skipped],
            },
        )
        await self.uow.commit()
        for block in result.blocks:
            await self.uow.session.refresh(block)
        await self._invalidate(ranges)
        return result

    async def _cancel_for_block(
        self, appointment: Appointment, block_reason: str, store: Store | None
    ) -> None:
        payload_before = {"status": appointment.status}
        appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            actor=self.actor,
            payload_before=payload_before,
            payload_after={
                "status": appointment.status,
                "reason": "blocked",
                "block_reason": block_reason,
            },
        )
        # El aviso al cliente sale por el outbox (fuera del request y con
        # reintento), nunca inline: un bloqueo de vacaciones puede cancelar
        # decenas de turnos.
        if is_deliverable_email(appointment.client_email):
            details = build_client_details(
                appointment, appointment.service, appointment.staff, store
            )
            details["client_email"] = appointment.client_email
            details["block_reason"] = block_reason
            self.uow.outbox.publish(
                store_id=self.actor.store_id,
                event_type=EVENT_CANCELLED_BY_BLOCK,
                payload=details,
            )

    async def _get_block(self, public_id: str) -> StaffBlock:
        result = await self.uow.session.execute(
            select(StaffBlock).where(
                StaffBlock.id == public_id, StaffBlock.store_id == self.actor.store_id
            )
        )
        block = result.scalar_one_or_none()
        if not block:
            raise ResourceNotFoundException(resource="Bloqueo", identifier=public_id)
        return block

    async def update_block(
        self, public_id: str, changes: dict[str, object]
    ) -> StaffBlock:
        block = await self._get_block(public_id)
        previous: Range = (block.start_time, block.end_time)
        if "starts_at" in changes and changes["starts_at"] is not None:
            block.start_time = changes["starts_at"]  # type: ignore[assignment]
        if "ends_at" in changes and changes["ends_at"] is not None:
            block.end_time = changes["ends_at"]  # type: ignore[assignment]
        if block.start_time >= block.end_time:
            raise ValidationException("El inicio debe ser anterior al fin")
        for key in ("reason", "is_active"):
            if key in changes and changes[key] is not None:
                setattr(block, key, changes[key])
        await self.uow.commit()
        await self.uow.session.refresh(block)
        await self._invalidate([previous, (block.start_time, block.end_time)])
        return block

    async def delete_block(self, public_id: str) -> None:
        block = await self._get_block(public_id)
        block.is_active = False
        await self.uow.commit()
        await self._invalidate([(block.start_time, block.end_time)])

    async def _invalidate(self, ranges: list[Range]) -> None:
        for starts_at, ends_at in ranges:
            await invalidate_availability_range(
                self.cache, self.actor.store_id, starts_at, ends_at
            )
