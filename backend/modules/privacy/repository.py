"""Consultas de los derechos del titular: todo acotado a UNA tienda.

Cada consulta lleva ``store_id`` ademas del cliente (defensa en profundidad
junto a la RLS, CLAUDE.md §2). Sin reglas de negocio: las decide el service.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.ledger.model import CustomerLedger
from modules.payments.model import LIVE_CHARGE_PAYMENT_STATUSES, Payment
from modules.payments.service import ACTIVE_APPOINTMENT_STATUSES
from modules.users.model import User, UserRole
from modules.waitlist.model import (
    OPEN_WAITLIST_STATUSES,
    WaitlistEntry,
    WaitlistStatus,
)


class DataSubjectRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def client_for_update(self, store_id: str, client_id: str) -> User | None:
        """El cliente de ESA tienda, lockeado (dos pedidos a la vez no se pisan).
        Personal, admins u otra tienda: None."""
        return (
            await self.db.execute(
                select(User)
                .where(
                    User.id == client_id,
                    User.store_id == store_id,
                    User.role == UserRole.CLIENT.value,
                    User.is_global_admin.is_(False),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def client(self, store_id: str, client_id: str) -> User | None:
        return (
            await self.db.execute(
                select(User).where(
                    User.id == client_id,
                    User.store_id == store_id,
                    User.role == UserRole.CLIENT.value,
                    User.is_global_admin.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def appointments(self, store_id: str, client_id: str) -> list[Appointment]:
        return list(
            (
                await self.db.execute(
                    select(Appointment)
                    .where(
                        Appointment.store_id == store_id,
                        Appointment.client_id == client_id,
                    )
                    .order_by(Appointment.starts_at, Appointment.id)
                )
            ).scalars()
        )

    async def payments(self, store_id: str, client_id: str) -> list[Payment]:
        return list(
            (
                await self.db.execute(
                    select(Payment)
                    .join(Appointment, Appointment.id == Payment.appointment_id)
                    .where(
                        Payment.store_id == store_id,
                        Appointment.store_id == store_id,
                        Appointment.client_id == client_id,
                    )
                    .order_by(Payment.created_at, Payment.id)
                )
            ).scalars()
        )

    async def ledger(self, store_id: str, client_id: str) -> list[CustomerLedger]:
        return list(
            (
                await self.db.execute(
                    select(CustomerLedger)
                    .where(
                        CustomerLedger.store_id == store_id,
                        CustomerLedger.client_id == client_id,
                    )
                    .order_by(CustomerLedger.created_at, CustomerLedger.id)
                )
            ).scalars()
        )

    async def waitlist(self, store_id: str, client_id: str) -> list[WaitlistEntry]:
        return list(
            (
                await self.db.execute(
                    select(WaitlistEntry)
                    .where(
                        WaitlistEntry.store_id == store_id,
                        WaitlistEntry.client_id == client_id,
                    )
                    .order_by(WaitlistEntry.created_at, WaitlistEntry.id)
                )
            ).scalars()
        )

    async def has_live_charge(self, store_id: str, client_id: str) -> bool:
        """Algun cobro vivo (``LIVE_CHARGE_PAYMENT_STATUSES``) de sus turnos."""
        return bool(
            await self.db.scalar(
                select(
                    exists().where(
                        Payment.store_id == store_id,
                        Payment.status.in_(sorted(LIVE_CHARGE_PAYMENT_STATUSES)),
                        Payment.appointment_id == Appointment.id,
                        Appointment.store_id == store_id,
                        Appointment.client_id == client_id,
                    )
                )
            )
        )

    async def has_upcoming_active(
        self, store_id: str, client_id: str, now: datetime
    ) -> bool:
        """Algun turno activo (``ACTIVE_APPOINTMENT_STATUSES``) que no empezo."""
        return bool(
            await self.db.scalar(
                select(
                    exists().where(
                        Appointment.store_id == store_id,
                        Appointment.client_id == client_id,
                        Appointment.status.in_(sorted(ACTIVE_APPOINTMENT_STATUSES)),
                        Appointment.starts_at > now,
                    )
                )
            )
        )

    async def scrub_appointments(
        self, store_id: str, client_id: str, values: dict[str, Any]
    ) -> None:
        await self.db.execute(
            update(Appointment)
            .where(
                Appointment.store_id == store_id,
                Appointment.client_id == client_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )

    async def scrub_ledger(self, store_id: str, client_id: str) -> None:
        await self.db.execute(
            update(CustomerLedger)
            .where(
                CustomerLedger.store_id == store_id,
                CustomerLedger.client_id == client_id,
            )
            .values(notes=None)
            .execution_options(synchronize_session=False)
        )

    async def scrub_waitlist(
        self, store_id: str, client_id: str, values: dict[str, Any]
    ) -> None:
        # Las abiertas se cierran: nadie puede recibir una oferta en un
        # buzon anonimizado, y el indice de "una abierta por telefono" no
        # admite el mismo telefono neutro en dos entradas abiertas.
        await self.db.execute(
            update(WaitlistEntry)
            .where(
                WaitlistEntry.store_id == store_id,
                WaitlistEntry.client_id == client_id,
                WaitlistEntry.status.in_(OPEN_WAITLIST_STATUSES),
            )
            .values(status=WaitlistStatus.CANCELLED.value)
            .execution_options(synchronize_session=False)
        )
        await self.db.execute(
            update(WaitlistEntry)
            .where(
                WaitlistEntry.store_id == store_id,
                WaitlistEntry.client_id == client_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
