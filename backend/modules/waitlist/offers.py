"""Encaje y oferta de cupos liberados a la lista de espera.

Regla de encaje (decision de producto, 2026-09-10): mismo profesional (o
"cualquiera") y que el servicio pedido quepa en el hueco, siempre que ese
profesional de ese servicio. No hace falta que sea el mismo servicio del
turno cancelado: un hueco de 30 minutos sirve para cualquier servicio de
hasta 30 minutos.

Se ofrece a UNA persona por vez, por orden de llegada, durante
``WAITLIST_OFFER_MINUTES``. Los cupos dentro de la antelacion minima de la
tienda no se mailean (el cliente no podria reservarlos por el portal): solo
se le avisa al dueno, que puede reservar a mano desde el panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.utils import ARGENTINA_TZ, ensure_utc_aware
from infrastructure.persistence.models.staff_service import StaffServiceModel
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.notifications.tasks import (
    enqueue_waitlist_offer_email,
    format_local_datetime,
    is_deliverable_email,
    rebook_url,
)
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.waitlist.model import WaitlistEntry, WaitlistStatus

logger = structlog.get_logger()


@dataclass(frozen=True)
class ReleasedSlot:
    store_id: str
    staff_id: str
    starts_at: datetime
    ends_at: datetime

    @classmethod
    def from_payload(cls, store_id: str, payload: dict[str, Any]) -> "ReleasedSlot":
        return cls(
            store_id=store_id,
            staff_id=str(payload["staff_id"]),
            starts_at=ensure_utc_aware(
                datetime.fromisoformat(str(payload["starts_at"]))
            ),
            ends_at=ensure_utc_aware(datetime.fromisoformat(str(payload["ends_at"]))),
        )

    @property
    def minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


@dataclass(frozen=True)
class OfferResult:
    candidates: int
    offered_entry_id: str | None
    owner_notified: bool


async def matching_entries(
    db: AsyncSession, slot: ReleasedSlot
) -> list[tuple[WaitlistEntry, Service]]:
    """Entradas en espera a las que les sirve este hueco, por orden de llegada."""
    servicios_del_staff = set(
        (
            await db.execute(
                select(StaffServiceModel.service_id).where(
                    StaffServiceModel.staff_id == slot.staff_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not servicios_del_staff:
        return []
    rows = await db.execute(
        select(WaitlistEntry, Service)
        .join(Service, WaitlistEntry.service_id == Service.id)
        .where(
            WaitlistEntry.store_id == slot.store_id,
            WaitlistEntry.is_active.is_(True),
            WaitlistEntry.status == WaitlistStatus.WAITING.value,
            WaitlistEntry.service_id.in_(servicios_del_staff),
            or_(
                WaitlistEntry.staff_id.is_(None),
                WaitlistEntry.staff_id == slot.staff_id,
            ),
            WaitlistEntry.window_starts_at <= slot.starts_at,
            WaitlistEntry.window_ends_at > slot.starts_at,
            # Quien ya dejo pasar este mismo cupo no lo recibe de nuevo.
            or_(
                WaitlistEntry.offered_starts_at.is_(None),
                WaitlistEntry.offered_starts_at != slot.starts_at,
                WaitlistEntry.offered_staff_id != slot.staff_id,
            ),
        )
        .order_by(WaitlistEntry.created_at.asc())
    )
    encajan: list[tuple[WaitlistEntry, Service]] = []
    for entry, service in rows.all():
        termina = slot.starts_at + timedelta(minutes=int(service.duration_minutes))
        if service.duration_minutes <= slot.minutes and termina <= ensure_utc_aware(
            entry.window_ends_at
        ):
            encajan.append((entry, service))
    return encajan


async def slot_still_free(db: AsyncSession, slot: ReleasedSlot) -> bool:
    result = await db.execute(
        select(Appointment.id)
        .where(
            Appointment.staff_id == slot.staff_id,
            Appointment.status.in_(
                [
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.PENDING_PAYMENT.value,
                    AppointmentStatus.CONFIRMED.value,
                ]
            ),
            and_(
                Appointment.starts_at < slot.ends_at,
                Appointment.ends_at > slot.starts_at,
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is None


def _owner_notification(
    store_id: str, slot: ReleasedSlot, staff_name: str, cuantos: int
) -> Notification:
    fecha, hora = format_local_datetime(slot.starts_at)
    return Notification(
        store_id=store_id,
        type=NotificationType.WAITLIST_SLOT_RELEASED.value,
        title="Se libero un hueco con gente en espera",
        body=(
            f"El {fecha} a las {hora} con {staff_name}: {cuantos} en lista de espera. "
            "Podes avisarles por WhatsApp o reservarles el turno desde Lista de espera."
        ),
    )


async def offer_released_slot(
    db: AsyncSession, slot: ReleasedSlot, *, now: datetime
) -> OfferResult:
    """Avisa al dueno y le ofrece el cupo al primero de la lista. No commitea."""
    encajan = await matching_entries(db, slot)
    if not encajan:
        return OfferResult(candidates=0, offered_entry_id=None, owner_notified=False)

    store = await db.get(Store, slot.store_id)
    staff = await db.get(Staff, slot.staff_id)
    staff_name = getattr(staff, "display_name", None) or "el profesional"
    db.add(_owner_notification(slot.store_id, slot, staff_name, len(encajan)))

    notice_hours = int(getattr(store, "min_booking_notice_hours", 2) or 0)
    if slot.starts_at < now + timedelta(hours=notice_hours):
        # Dentro de la antelacion minima el cliente no puede reservar por el
        # portal: queda en manos del dueno (WhatsApp o alta desde el panel).
        return OfferResult(
            candidates=len(encajan), offered_entry_id=None, owner_notified=True
        )

    entry, service = encajan[0]
    entry.status = WaitlistStatus.OFFERED.value
    entry.notified_at = now
    entry.offer_expires_at = now + timedelta(minutes=settings.WAITLIST_OFFER_MINUTES)
    entry.offered_staff_id = slot.staff_id
    entry.offered_starts_at = slot.starts_at
    entry.offered_ends_at = slot.starts_at + timedelta(
        minutes=int(service.duration_minutes)
    )

    if is_deliverable_email(entry.client_email):
        base = settings.FRONTEND_URL.rstrip("/")
        slug = getattr(store, "slug", None)
        fecha_iso = slot.starts_at.astimezone(ARGENTINA_TZ).date().isoformat()
        link = rebook_url(base, slug, service, staff)
        await enqueue_waitlist_offer_email(
            email=entry.client_email,
            details={
                "public_id": entry.id,
                "client_name": entry.client_name,
                "service": service.name,
                "staff": staff_name,
                "staff_kind": getattr(staff, "kind", None) or "person",
                "starts_at": slot.starts_at.isoformat(),
                "store_name": getattr(store, "name", "") or "",
                "store_phone": getattr(store, "whatsapp_number", None) or "",
                "booking_url": f"{base}/b/{slug}" if slug else "",
                "offer_url": f"{link}&date={fecha_iso}" if link else "",
                "offer_minutes": settings.WAITLIST_OFFER_MINUTES,
            },
        )
    logger.info(
        "waitlist_slot_offered",
        store_id=slot.store_id,
        entry_id=entry.id,
        candidates=len(encajan),
    )
    return OfferResult(
        candidates=len(encajan), offered_entry_id=entry.id, owner_notified=True
    )


async def expire_lapsed_offers(db: AsyncSession, *, now: datetime) -> dict[str, int]:
    """Ofertas vencidas vuelven a la cola; si el cupo sigue libre, va al siguiente."""
    rows = await db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.is_active.is_(True),
            WaitlistEntry.status == WaitlistStatus.OFFERED.value,
            WaitlistEntry.offer_expires_at.is_not(None),
            WaitlistEntry.offer_expires_at <= now,
        )
    )
    lapsed = list(rows.scalars().all())
    reofrecidos = 0
    for entry in lapsed:
        entry.status = WaitlistStatus.WAITING.value
        entry.offer_expires_at = None
        if entry.offered_staff_id and entry.offered_starts_at and entry.offered_ends_at:
            slot = ReleasedSlot(
                store_id=entry.store_id,
                staff_id=entry.offered_staff_id,
                starts_at=ensure_utc_aware(entry.offered_starts_at),
                ends_at=ensure_utc_aware(entry.offered_ends_at),
            )
            await db.flush()
            if await slot_still_free(db, slot):
                result = await offer_released_slot(db, slot, now=now)
                if result.offered_entry_id:
                    reofrecidos += 1

    vencidas = await db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.is_active.is_(True),
            WaitlistEntry.status.in_(
                [WaitlistStatus.WAITING.value, WaitlistStatus.OFFERED.value]
            ),
            WaitlistEntry.window_ends_at <= now,
        )
    )
    expiradas = 0
    for entry in vencidas.scalars().all():
        entry.status = WaitlistStatus.EXPIRED.value
        expiradas += 1
    return {"lapsed": len(lapsed), "reoffered": reofrecidos, "expired": expiradas}


async def mark_booked(
    db: AsyncSession,
    *,
    store_id: str,
    client_phone: str,
    service_id: str,
    starts_at: datetime,
) -> int:
    """Cierra las entradas abiertas de ese telefono que cubre la reserva hecha."""
    rows = await db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.store_id == store_id,
            WaitlistEntry.is_active.is_(True),
            WaitlistEntry.status.in_(
                [WaitlistStatus.WAITING.value, WaitlistStatus.OFFERED.value]
            ),
            WaitlistEntry.client_phone == client_phone,
            WaitlistEntry.service_id == service_id,
            WaitlistEntry.window_starts_at <= starts_at,
            WaitlistEntry.window_ends_at > starts_at,
        )
    )
    cerradas = 0
    for entry in rows.scalars().all():
        entry.status = WaitlistStatus.BOOKED.value
        entry.offer_expires_at = None
        cerradas += 1
    return cerradas
