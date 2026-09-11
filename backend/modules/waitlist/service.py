"""Lista de espera: alta, consulta, baja y reserva a mano. Dueno de la transaccion."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import AvailabilityCacheClient, invalidate_availability
from core.exceptions import AppException, ResourceNotFoundException
from core.utils import ensure_utc_aware
from infrastructure.persistence.models.staff_service import StaffServiceModel
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.tasks import build_client_details, enqueue_confirmation_email
from modules.public_api.repository import PublicRepository
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.waitlist.model import OPEN_WAITLIST_STATUSES, WaitlistEntry, WaitlistStatus
from modules.waitlist.offers import mark_booked

WaitlistRow = tuple[WaitlistEntry, Service, Staff | None]


class WaitlistDuplicateException(AppException):
    def __init__(self) -> None:
        super().__init__(
            message="Ya estas anotado en la lista de espera para ese servicio y ventana",
            http_status=HTTPStatus.CONFLICT,
            error_code="WAITLIST_DUPLICATE",
        )


class WaitlistService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.public_repo = PublicRepository(db)

    # ------------------------------------------------------------------ alta
    async def join(
        self,
        *,
        store: Store,
        service_public_id: str,
        staff_public_id: str | None,
        window_starts_at: datetime,
        window_ends_at: datetime,
        client_name: str,
        client_phone: str,
        client_email: str | None,
        notes: str | None,
    ) -> WaitlistRow:
        service = await self._service(store.id, service_public_id)
        staff = await self._staff_for(store.id, staff_public_id, service)
        window_starts_at = ensure_utc_aware(window_starts_at)
        window_ends_at = ensure_utc_aware(window_ends_at)
        if window_ends_at <= datetime.now(timezone.utc):
            raise AppException(
                message="La ventana ya paso",
                http_status=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="WAITLIST_WINDOW_PAST",
            )
        if await self._open_duplicate(
            store.id, client_phone, service.id, window_starts_at
        ):
            raise WaitlistDuplicateException()

        client = await self.public_repo.get_or_create_client(
            store.id, client_phone, client_name, client_email
        )
        entry = WaitlistEntry(
            store_id=store.id,
            client_id=client.id,
            client_name=client_name.strip(),
            client_phone=client_phone,
            client_email=client_email or None,
            service_id=service.id,
            staff_id=staff.id if staff else None,
            window_starts_at=window_starts_at,
            window_ends_at=window_ends_at,
            notes=(notes or "").strip() or None,
        )
        self.db.add(entry)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            # El indice unico parcial atrapa la carrera entre dos altas iguales.
            await self.db.rollback()
            raise WaitlistDuplicateException() from exc
        await self.db.refresh(entry)
        return (entry, service, staff)

    # --------------------------------------------------------------- lectura
    async def list_open(self, store_id: str) -> list[WaitlistRow]:
        rows = await self.db.execute(
            select(WaitlistEntry, Service, Staff)
            .join(Service, WaitlistEntry.service_id == Service.id)
            .outerjoin(Staff, WaitlistEntry.staff_id == Staff.id)
            .where(
                WaitlistEntry.store_id == store_id,
                WaitlistEntry.is_active.is_(True),
                WaitlistEntry.status.in_(OPEN_WAITLIST_STATUSES),
            )
            .order_by(
                WaitlistEntry.window_starts_at.asc(), WaitlistEntry.created_at.asc()
            )
        )
        return [(r[0], r[1], r[2]) for r in rows.all()]

    async def list_for_client(
        self, store_id: str, client_phone: str
    ) -> list[WaitlistRow]:
        rows = await self.db.execute(
            select(WaitlistEntry, Service, Staff)
            .join(Service, WaitlistEntry.service_id == Service.id)
            .outerjoin(Staff, WaitlistEntry.staff_id == Staff.id)
            .where(
                WaitlistEntry.store_id == store_id,
                WaitlistEntry.is_active.is_(True),
                WaitlistEntry.client_phone == client_phone,
                WaitlistEntry.status.in_(OPEN_WAITLIST_STATUSES),
            )
            .order_by(WaitlistEntry.window_starts_at.asc())
        )
        return [(r[0], r[1], r[2]) for r in rows.all()]

    async def get_open(self, store_id: str, entry_id: str) -> WaitlistEntry:
        result = await self.db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.id == entry_id,
                WaitlistEntry.store_id == store_id,
                WaitlistEntry.is_active.is_(True),
                WaitlistEntry.status.in_(OPEN_WAITLIST_STATUSES),
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise ResourceNotFoundException("Entrada de lista de espera", entry_id)
        return entry

    # ------------------------------------------------------------------ baja
    async def cancel(self, entry: WaitlistEntry) -> WaitlistEntry:
        entry.status = WaitlistStatus.CANCELLED.value
        entry.offer_expires_at = None
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    # ------------------------------------------------- reserva desde el panel
    async def book_from_panel(
        self,
        *,
        store: Store,
        entry: WaitlistEntry,
        starts_at: datetime,
        staff_public_id: str | None,
        cache: AvailabilityCacheClient,
    ) -> tuple[Appointment, Service, Staff]:
        """El dueno reserva para alguien de la lista: confirmado, sin antelacion minima.

        Reutiliza el alta publica (lock del profesional, bloqueos, choques y
        buffer) con estado inicial confirmado porque lo hace la tienda.
        """
        service = await self.db.get(Service, entry.service_id)
        if not service:
            raise ResourceNotFoundException("Servicio", entry.service_id)
        # Lock de la entrada antes de usarla: dos pestanias del panel sobre la
        # misma persona creaban dos turnos confirmados desde una sola entrada.
        bloqueada = await self.db.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == entry.id).with_for_update()
        )
        entry = bloqueada.scalar_one()
        if entry.status not in OPEN_WAITLIST_STATUSES:
            raise AppException(
                message="Esa persona ya no esta en la lista de espera",
                http_status=HTTPStatus.CONFLICT,
                error_code="WAITLIST_ENTRY_CLOSED",
            )
        try:
            appointment, service, staff = await self._create_confirmed(
                store, entry, service, starts_at, staff_public_id
            )
        except ValueError as exc:
            # Mismo mapeo que la reserva publica: choque, bloqueo o profesional
            # que no da el servicio son 409, no un 500.
            await self.db.rollback()
            raise AppException(
                message=str(exc),
                http_status=HTTPStatus.CONFLICT,
                error_code="APPOINTMENT_CONFLICT",
            ) from exc
        entry.status = WaitlistStatus.BOOKED.value
        entry.offer_expires_at = None
        await mark_booked(
            self.db,
            store_id=store.id,
            client_phone=entry.client_phone,
            service_id=service.id,
            starts_at=appointment.starts_at,
        )
        await self.db.commit()
        await invalidate_availability(cache, store.id, appointment.starts_at)
        await enqueue_confirmation_email(
            email=entry.client_email,
            details=build_client_details(appointment, service, staff, store),
        )
        return appointment, service, staff

    async def _create_confirmed(
        self,
        store: Store,
        entry: WaitlistEntry,
        service: Service,
        starts_at: datetime,
        staff_public_id: str | None,
    ) -> tuple[Appointment, Service, Staff]:
        client = await self.public_repo.get_client_by_phone(
            store.id, entry.client_phone
        )
        if client is None:
            raise ResourceNotFoundException("Cliente", entry.client_phone)
        return await self.public_repo.create_appointment(
            store_id=store.id,
            service_public_id=service.public_id,
            staff_public_id=staff_public_id or entry.staff_id,
            starts_at=ensure_utc_aware(starts_at),
            client=client,
            notes=entry.notes,
            intake_answers=None,
            idempotency_key=f"waitlist-{entry.id}-{int(ensure_utc_aware(starts_at).timestamp())}",
            initial_status=AppointmentStatus.CONFIRMED.value,
            buffer_minutes=int(getattr(store, "buffer_minutes", 0) or 0),
            price_amount=Decimal(str(service.price or 0)),
        )

    # -------------------------------------------------------------- privados
    async def _service(self, store_id: str, public_id: str) -> Service:
        result = await self.db.execute(
            select(Service).where(
                Service.public_id == public_id,
                Service.store_id == store_id,
                Service.is_active.is_(True),
            )
        )
        service = result.scalar_one_or_none()
        if not service:
            raise ResourceNotFoundException("Servicio", public_id)
        return service

    async def _staff_for(
        self, store_id: str, staff_public_id: str | None, service: Service
    ) -> Staff | None:
        if not staff_public_id:
            return None
        result = await self.db.execute(
            select(Staff).where(
                Staff.id == staff_public_id,
                Staff.store_id == store_id,
                Staff.is_active.is_(True),
            )
        )
        staff = result.scalar_one_or_none()
        if not staff:
            raise ResourceNotFoundException("Profesional", staff_public_id)
        vinculo = await self.db.execute(
            select(StaffServiceModel.staff_id).where(
                StaffServiceModel.staff_id == staff.id,
                StaffServiceModel.service_id == service.id,
            )
        )
        if vinculo.scalar_one_or_none() is None:
            raise AppException(
                message="El profesional no realiza el servicio seleccionado",
                http_status=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="STAFF_SERVICE_MISMATCH",
            )
        return staff

    async def _open_duplicate(
        self, store_id: str, phone: str, service_id: str, window_starts_at: datetime
    ) -> bool:
        result = await self.db.execute(
            select(WaitlistEntry.id).where(
                WaitlistEntry.store_id == store_id,
                WaitlistEntry.client_phone == phone,
                WaitlistEntry.service_id == service_id,
                WaitlistEntry.window_starts_at == window_starts_at,
                WaitlistEntry.status.in_(OPEN_WAITLIST_STATUSES),
                WaitlistEntry.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None


def to_row_dict(row: WaitlistRow, *, show_contact: bool) -> dict[str, Any]:
    entry, service, staff = row
    return {
        "public_id": entry.id,
        "status": entry.status,
        "service_id": service.public_id,
        "service_name": service.name,
        "staff_id": staff.id if staff else None,
        "staff_name": staff.display_name if staff else None,
        "window_starts_at": entry.window_starts_at,
        "window_ends_at": entry.window_ends_at,
        "client_name": entry.client_name,
        "client_phone": entry.client_phone if show_contact else None,
        "client_email": entry.client_email if show_contact else None,
        "notes": entry.notes,
        "notified_at": entry.notified_at,
        "offer_expires_at": entry.offer_expires_at,
        "offered_starts_at": entry.offered_starts_at,
        "offered_staff_id": entry.offered_staff_id,
        "created_at": entry.created_at,
    }
