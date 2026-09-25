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
- ``update_block`` pasa por ese mismo nucleo sobre los tramos que el bloqueo
  EMPIEZA a cubrir (mover, agrandar, reactivar). Hasta la auditoria 2
  (AUD2-B1-01) el PATCH no lockeaba ni miraba turnos: agrandar un bloqueo
  dejaba adentro los mismos huerfanos que el alta evita.
- Los commits viven aca, no en el router (patron de ``appointments``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TypeVar, cast

from sqlalchemy import select

from core.availability_cache import (
    AvailabilityCacheClient,
    invalidate_availability_range,
    invalidate_store_availability,
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
from core.utils import ARGENTINA_TZ, ensure_utc_aware
from modules.appointment_blocks.schemas import block_instants_error, block_range_error
from modules.appointments.model import Appointment, AppointmentStatus
from modules.audit.model import AuditAction
from modules.notifications.tasks import build_client_details, is_deliverable_email
from modules.payments.model import JsonValue, Payment
from modules.payments.service import expire_live_charge
from modules.staff.model import Staff, StaffBlock
from modules.stores.model import Store
from modules.users.model import User
from modules.waitlist.events import EVENT_SLOT_RELEASED, slot_released_payload

EVENT_CANCELLED_BY_BLOCK = "appointment.cancelled_by_block"

Range = tuple[datetime, datetime]
T = TypeVar("T")

# Hasta cuantos dias se invalida la cache dia por dia (un INCR + EXPIRE por
# dia, AUD2-B1-10). Por encima, un solo INCR de la generacion de la tienda:
# un bloqueo de meses cambia la disponibilidad de todos esos dias igual, y
# tirar la cache entera cuesta lo mismo que tirar la de un dia.
MAX_DAYS_INVALIDATED_ONE_BY_ONE = 31


def days_covered(ranges: list[Range]) -> int:
    """Cantidad de dias locales que tocan los rangos, sumados (funcion pura).

    Cota superior de lo que ``invalidate_availability_range`` recorreria: un
    dia que aparece en dos rangos cuenta dos veces, que es lo que costaria.
    """
    total = 0
    for starts_at, ends_at in ranges:
        inicio = ensure_utc_aware(starts_at).astimezone(ARGENTINA_TZ).date()
        fin = ensure_utc_aware(ends_at).astimezone(ARGENTINA_TZ).date()
        total += (fin - inicio).days + 1
    return total


def changed(changes: dict[str, object], key: str, current: T) -> T:
    """Valor que deja el PATCH para ``key`` (ausente o null = sin cambio)."""
    value = changes.get(key)
    return current if value is None else cast(T, value)


def added_ranges(
    previous: Range, was_active: bool, planned: Range, will_be_active: bool
) -> list[Range]:
    """Tramos que el bloqueo EMPIEZA a cubrir con el cambio (funcion pura).

    Complemento exacto de ``_publish_released``: ahi se mira lo que se
    libera, aca lo que se agrega. Un bloqueo inactivo no cubre nada, asi que
    reactivarlo agrega el rango entero y desactivarlo no agrega nada.
    """
    if not will_be_active:
        return []
    new_start = ensure_utc_aware(planned[0])
    new_end = ensure_utc_aware(planned[1])
    if not was_active:
        return [(new_start, new_end)]
    prev_start = ensure_utc_aware(previous[0])
    prev_end = ensure_utc_aware(previous[1])
    added: list[Range] = []
    if new_start < prev_start:
        added.append((new_start, min(new_end, prev_start)))
    if prev_end < new_end:
        added.append((max(new_start, prev_end), new_end))
    return added


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
    # Su cobro (a lo sumo uno), para vencerlo si es un cobro vivo al cancelar.
    payment: Payment | None = None

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

    async def _payments_by_appointment(
        self, appointment_ids: list[str], *, lock: bool = False
    ) -> dict[str, Payment]:
        """Pago de cada turno en UNA consulta (regla 12, B1-14).

        Antes era un ``get_by_appointment`` por turno afectado, con los locks
        de los profesionales tomados. Hay a lo sumo un pago por turno
        (``uq_payments_store_appointment``), asi que el dict es exacto.

        ``lock``: al escribir, los pagos se lockean DESPUES de los turnos
        (profesional -> turnos -> pagos; regla 7, turno -> pago) para poder
        vencer el cobro vivo de los que se cancelan (revision de perf/f4-pay).
        """
        if not appointment_ids:
            return {}
        consulta = select(Payment).where(
            Payment.appointment_id.in_(appointment_ids),
            Payment.store_id == self.actor.store_id,
        )
        if lock:
            consulta = consulta.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.uow.session.execute(consulta)
        return {payment.appointment_id: payment for payment in result.scalars()}

    async def _classify(
        self, appointments: list[Appointment], *, lock: bool = False
    ) -> list[AffectedAppointment]:
        affected: list[AffectedAppointment] = []
        payments = await self._payments_by_appointment(
            [
                appointment.id
                for appointment in appointments
                if appointment.status != AppointmentStatus.PENDING_PAYMENT.value
            ],
            lock=lock,
        )
        for appointment in appointments:
            if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
                affected.append(AffectedAppointment(appointment, "pending_payment"))
                continue
            payment = payments.get(appointment.id)
            if payment is not None and payment.is_accredited:
                affected.append(AffectedAppointment(appointment, "has_deposit"))
                continue
            affected.append(AffectedAppointment(appointment, None, payment))
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
        result = BlockCreationResult(blocks=[])
        result.cancelled, result.skipped = await self._lock_and_resolve_affected(
            staff_ids=staff_ids,
            ranges=ranges,
            reason=reason,
            cancel_affected=cancel_affected,
        )

        for member_id in staff_ids:
            for starts_at, ends_at in ranges:
                block = StaffBlock(
                    store_id=self.actor.store_id,
                    staff_id=member_id,
                    start_time=starts_at,
                    end_time=ends_at,
                    reason=reason,
                    is_active=True,
                )
                self.uow.session.add(block)
                result.blocks.append(block)
        # Los ids se generan en el flush; la auditoria los necesita.
        await self.uow.session.flush()

        await self.uow.audit.log(
            action=AuditAction.CREATE,
            resource_type="AppointmentBlock",
            resource_id=result.blocks[0].id if result.blocks else "",
            store_id=self.actor.store_id,
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
        # Sin refresh por bloqueo (B1-14: era un SELECT por cada uno, hasta
        # 600 en un cierre largo). Todas las columnas que lee la respuesta
        # (id, staff, rango, reason, is_active) se asignan del lado de Python
        # y la sesion no expira al commitear (expire_on_commit=False).
        await self._invalidate(ranges)
        return result

    async def _lock_and_resolve_affected(
        self,
        *,
        staff_ids: list[str],
        ranges: list[Range],
        reason: str,
        cancel_affected: bool,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Lock, relectura bajo lock y guarda de turnos afectados.

        Nucleo compartido por el alta y por la edicion (AUD2-B1-01). Sin
        ``cancel_affected`` levanta 409 antes de escribir nada; con el flag
        (solo administradores) cancela los cancelables y devuelve
        ``(cancelados, salteados)``. Con ``ranges`` vacio (un PATCH que solo
        achica o desactiva) toma igual el lock y no lee turnos.
        """
        # Orden total por id en una sentencia (S-11): dos escrituras
        # simultaneas sobre los mismos profesionales no pueden cruzarse en
        # deadlock.
        await self.uow.appointments.lock_staff_rows(staff_ids)
        appointments = await self.uow.appointments.list_active_overlapping(
            self.actor.store_id, staff_ids, ranges, lock=True
        )
        affected = await self._classify(appointments, lock=True)
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
        cancelled: list[str] = []
        skipped: list[tuple[str, str]] = []
        if affected:
            if not has_any_role(self.actor, STORE_MANAGERS):
                raise PermissionDeniedException(
                    action="Solo un administrador puede cancelar turnos en bloque"
                )
            store = await self.uow.session.get(Store, self.actor.store_id)
            for item in affected:
                if not item.cancellable:
                    skipped.append((item.appointment.public_id, item.reason or ""))
                    continue
                await self._cancel_for_block(item, reason, store)
                cancelled.append(item.appointment.public_id)
        return cancelled, skipped

    async def _cancel_for_block(
        self, item: AffectedAppointment, block_reason: str, store: Store | None
    ) -> None:
        """Cancela un turno cubierto por el bloqueo y vence su cobro vivo.

        Regla del dueno (D2, revision de perf/f4-pay 2026-09-25): lo que hace
        el personal vence el cobro. Antes el turno se cancelaba con un link
        del panel en ``pending``/``rejected`` vivo en Mercado Pago. Mismo
        camino que cancelar desde la agenda (``expire_live_charge``), en esta
        transaccion; el turno y despues su pago ya estan lockeados.
        """
        appointment = item.appointment
        payload_before = {"status": appointment.status}
        appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        payload_after: dict[str, JsonValue] = {
            "status": appointment.status,
            "reason": "blocked",
            "block_reason": block_reason,
        }
        vencido = expire_live_charge(
            self.uow.session,
            item.payment,
            reason="block_cancel",
            released_by=self.actor.public_id,
        )
        if vencido is not None:
            payload_after["expired_payment_id"] = vencido.id
        await self.uow.audit.log(
            action=AuditAction.STATUS_CHANGE,
            resource_type="Appointment",
            resource_id=appointment.public_id,
            store_id=appointment.store_id,
            actor=self.actor,
            payload_before=payload_before,
            payload_after=payload_after,
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

    @staticmethod
    def _planned_range(block: StaffBlock, changes: dict[str, object]) -> Range:
        """Rango que dejaria el PATCH, calculado ANTES de tocar el bloqueo.

        Se decide sobre valores sueltos y no sobre la fila ya mutada porque
        la relectura bajo lock hace autoflush: con la fila mutada, un 409
        habria escrito el rango nuevo antes de rechazarlo.
        """
        starts_at: datetime = changed(changes, "starts_at", block.start_time)
        ends_at: datetime = changed(changes, "ends_at", block.end_time)
        # Misma regla que los schemas del alta, incluido el tope de duracion
        # (AUD2-B1-10): el schema del PATCH no puede medirla porque puede
        # venir un solo extremo.
        # Solo los extremos cuyo VALOR cambia caen en la ventana de fechas: el
        # formulario de la agenda reenvia siempre los dos, y editar el motivo
        # de un bloqueo viejo no puede revalidar un rango que no se toca.
        nuevos = [
            valor
            for valor, guardado in (
                (changes.get("starts_at"), block.start_time),
                (changes.get("ends_at"), block.end_time),
            )
            if isinstance(valor, datetime)
            and ensure_utc_aware(valor) != ensure_utc_aware(guardado)
        ]
        error = block_instants_error(*nuevos) or block_range_error(starts_at, ends_at)
        if error:
            raise ValidationException(error)
        return (starts_at, ends_at)

    async def update_block(
        self,
        public_id: str,
        changes: dict[str, object],
        *,
        cancel_affected: bool = False,
    ) -> StaffBlock:
        block = await self._get_block(public_id)
        previous: Range = (block.start_time, block.end_time)
        was_active = bool(block.is_active)
        planned = self._planned_range(block, changes)
        # Mismo camino que el alta (AUD2-B1-01): lo que el bloqueo empieza a
        # cubrir se decide con el profesional lockeado; achicar o desactivar
        # no cubre nada nuevo y no pide confirmacion.
        await self._lock_and_resolve_affected(
            staff_ids=[block.staff_id],
            ranges=added_ranges(
                previous,
                was_active,
                planned,
                bool(changed(changes, "is_active", was_active)),
            ),
            reason=str(changed(changes, "reason", block.reason)),
            cancel_affected=cancel_affected,
        )
        for key in ("starts_at", "ends_at", "reason", "is_active"):
            if changes.get(key) is not None:
                setattr(block, key, changes[key])
        self._publish_released(block, previous, was_active)
        await self.uow.commit()
        await self.uow.session.refresh(block)
        await self._invalidate([previous, (block.start_time, block.end_time)])
        return block

    async def delete_block(self, public_id: str) -> None:
        # Borrar es desactivar: un solo camino decide que tramo queda libre y
        # se lo avisa a la lista de espera (B1-18).
        await self.update_block(public_id, {"is_active": False})

    def _publish_released(
        self, block: StaffBlock, previous: Range, was_active: bool
    ) -> None:
        """Publica cada tramo que el bloqueo dejo de cubrir.

        Antes solo ``delete`` avisaba: ``PATCH`` con ``is_active=false`` (el
        mismo estado final) o achicando/moviendo el rango liberaba agenda sin
        que nadie de la lista se enterara (B1-18). El motivo es siempre
        ``block_deleted``: un rango liberado no cae en la grilla, se le avisa
        al duenio y no se le ofrece al cliente (``ReleasedSlot.aligned_to_grid``).
        """
        if not was_active:
            return  # no bloqueaba nada: no hay nada que liberar
        prev_start = ensure_utc_aware(previous[0])
        prev_end = ensure_utc_aware(previous[1])
        freed: list[Range] = []
        if not block.is_active:
            freed.append((prev_start, prev_end))
        else:
            new_start = ensure_utc_aware(block.start_time)
            new_end = ensure_utc_aware(block.end_time)
            if prev_start < new_start:
                freed.append((prev_start, min(prev_end, new_start)))
            if new_end < prev_end:
                freed.append((max(prev_start, new_end), prev_end))
        for starts_at, ends_at in freed:
            self.uow.outbox.publish(
                store_id=self.actor.store_id,
                event_type=EVENT_SLOT_RELEASED,
                payload=slot_released_payload(
                    staff_id=block.staff_id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    reason="block_deleted",
                ),
            )

    async def _invalidate(self, ranges: list[Range]) -> None:
        """Invalida la disponibilidad de los dias que tocan los rangos.

        Dia por dia hasta ``MAX_DAYS_INVALIDATED_ONE_BY_ONE``; por encima, un
        solo ``INCR`` de la generacion de la tienda (AUD2-B1-10). Sin el tope,
        un bloqueo largo o un lote recurrente disparaba miles de comandos a
        Redis con la transaccion ya commiteada y el request colgado.
        """
        try:
            muchos = days_covered(ranges) > MAX_DAYS_INVALIDATED_ONE_BY_ONE
        except OverflowError, ValueError:
            # Una fila imposible ya guardada (anio 0001 o 9999, de antes de
            # las cotas de fechas) no tiene dia local representable: se
            # invalida la tienda entera en vez de dar 500 despues del commit
            # (revision de perf/f4-back, mismo criterio que 8250b86).
            muchos = True
        if muchos:
            await invalidate_store_availability(self.cache, self.actor.store_id)
            return
        for starts_at, ends_at in ranges:
            await invalidate_availability_range(
                self.cache, self.actor.store_id, starts_at, ends_at
            )
