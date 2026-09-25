"""Derechos del titular ejercidos por la tienda (PV-05, L3-06; 2026-09-25).

La tienda es la responsable de los datos de sus clientes y tiene que poder
atender un pedido de acceso (art. 14 Ley 25.326) o de supresion (art. 16).
Dueno de la transaccion (commit solo aca, CLAUDE.md §2).

- ``export``: los datos del cliente y sus turnos, cobros, fiado y lista de
  espera de ESTA tienda.
- ``anonymize``: reemplaza nombre, telefono, email, respuestas de la reserva
  y notas por valores neutros y deja al cliente inactivo. Conserva importes,
  fechas y estados (contabilidad). No revoca nada mas: un cliente no tiene
  sesiones del panel. Se rechaza (409) con un cobro vivo o un turno activo a
  futuro: primero se cierra eso (cobrar o cancelar), despues se anonimiza.

Cada pedido deja una fila de auditoria con el hecho (quien, cuando, sobre que
id), nunca con los datos. Solo cuentas con rol cliente de la tienda del
admin: personal, admins u otra tienda son 404 neutro.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, ResourceNotFoundException
from modules.audit.model import AuditAction
from modules.audit.repository import AuditRepository
from modules.privacy.repository import DataSubjectRepository
from modules.privacy.schemas import (
    ClientDataExport,
    ExportedAppointment,
    ExportedClient,
    ExportedLedgerMovement,
    ExportedPayment,
    ExportedWaitlistEntry,
)
from modules.users.model import User

ANONYMIZED_NAME = "Cliente anonimizado"
# Neutro y no entregable (``is_deliverable_email`` descarta ``.noreply``),
# unico por cliente (``users.email`` es unico) y en minusculas
# (``ck_users_email_lower``).
ANONYMIZED_EMAIL_DOMAIN = "anonimizado.noreply"
# ``waitlist_entries.client_phone`` es NOT NULL.
ANONYMIZED_PHONE = "0"


def anonymized_email(client_id: str) -> str:
    return f"anonimo-{client_id.lower()}@{ANONYMIZED_EMAIL_DOMAIN}"


class ClientHasLiveChargeException(AppException):
    def __init__(self) -> None:
        super().__init__(
            message=(
                "El cliente tiene un cobro abierto. Cobralo o cancelalo antes de "
                "anonimizarlo."
            ),
            http_status=HTTPStatus.CONFLICT,
            error_code="CLIENT_HAS_LIVE_CHARGE",
        )


class ClientHasActiveAppointmentsException(AppException):
    def __init__(self) -> None:
        super().__init__(
            message=(
                "El cliente tiene turnos activos a futuro. Cancelalos antes de "
                "anonimizarlo."
            ),
            http_status=HTTPStatus.CONFLICT,
            error_code="CLIENT_HAS_ACTIVE_APPOINTMENTS",
        )


class DataSubjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = DataSubjectRepository(db)
        self.audit = AuditRepository(db)

    async def export(self, *, client_id: str, actor: User) -> ClientDataExport:
        store_id = actor.store_id
        client = await self.repo.client(store_id, client_id)
        if client is None:
            raise ResourceNotFoundException("Cliente", client_id)
        export = ClientDataExport(
            exported_at=datetime.now(timezone.utc),
            store_id=store_id,
            client=_client(client),
            appointments=[
                _appointment(a)
                for a in await self.repo.appointments(store_id, client.id)
            ],
            payments=[
                _payment(p) for p in await self.repo.payments(store_id, client.id)
            ],
            ledger=[_ledger(m) for m in await self.repo.ledger(store_id, client.id)],
            waitlist=[
                _waitlist(w) for w in await self.repo.waitlist(store_id, client.id)
            ],
        )
        await self._audit(AuditAction.EXPORT, client.id, store_id, actor)
        await self.db.commit()
        return export

    async def anonymize(self, *, client_id: str, actor: User) -> None:
        store_id = actor.store_id
        client = await self.repo.client_for_update(store_id, client_id)
        if client is None:
            raise ResourceNotFoundException("Cliente", client_id)
        if await self.repo.has_live_charge(store_id, client.id):
            raise ClientHasLiveChargeException()
        if await self.repo.has_upcoming_active(
            store_id, client.id, datetime.now(timezone.utc)
        ):
            raise ClientHasActiveAppointmentsException()

        client.first_name = ANONYMIZED_NAME
        client.last_name = None
        client.phone = None
        client.email = anonymized_email(client.id)
        client.is_active = False
        await self.repo.scrub_appointments(
            store_id,
            client.id,
            {
                "client_name": ANONYMIZED_NAME,
                "client_email": None,
                "client_phone": None,
                "notes": None,
                "notes_staff": None,
                "intake_answers": {},
            },
        )
        await self.repo.scrub_ledger(store_id, client.id)
        await self.repo.scrub_waitlist(
            store_id,
            client.id,
            {
                "client_name": ANONYMIZED_NAME,
                "client_phone": ANONYMIZED_PHONE,
                "client_email": None,
                "notes": None,
            },
        )
        await self._audit(AuditAction.ANONYMIZE, client.id, store_id, actor)
        await self.db.commit()

    async def _audit(
        self, action: AuditAction, client_id: str, store_id: str, actor: User
    ) -> None:
        # Solo el hecho: el recurso es el id del cliente, nunca sus datos.
        await self.audit.log(
            action=action,
            resource_type="User",
            resource_id=client_id,
            store_id=store_id,
            actor=actor,
            payload_after={"data_subject_request": action.value},
        )


def _client(user: User) -> ExportedClient:
    return ExportedClient(
        public_id=user.public_id,
        full_name=user.full_name,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone=user.phone,
        is_active=bool(user.is_active),
        created_at=user.created_at,
    )


def _appointment(a: Any) -> ExportedAppointment:
    return ExportedAppointment(
        public_id=a.public_id,
        starts_at=a.starts_at,
        ends_at=a.ends_at,
        status=str(a.status),
        service_id=a.service_id,
        staff_id=a.staff_id,
        client_name=a.client_name,
        client_email=a.client_email,
        client_phone=a.client_phone,
        notes=a.notes,
        notes_staff=a.notes_staff,
        intake_answers=a.intake_answers,
        price_amount=a.price_amount,
        terms_accepted_at=a.terms_accepted_at,
        terms_version=a.terms_version,
        privacy_version=a.privacy_version,
        cancelled_at=a.cancelled_at,
        completed_at=a.completed_at,
    )


def _payment(p: Any) -> ExportedPayment:
    return ExportedPayment(
        public_id=p.id,
        appointment_id=p.appointment_id,
        provider=p.provider,
        amount=p.amount,
        currency=p.currency,
        status=p.status,
        paid_at=p.paid_at,
        created_at=p.created_at,
    )


def _ledger(m: Any) -> ExportedLedgerMovement:
    return ExportedLedgerMovement(
        public_id=m.id,
        movement_type=m.movement_type,
        amount=m.amount,
        balance_after=m.balance_after,
        appointment_id=m.appointment_id,
        notes=m.notes,
        created_at=m.created_at,
    )


def _waitlist(w: Any) -> ExportedWaitlistEntry:
    return ExportedWaitlistEntry(
        public_id=w.public_id,
        status=w.status,
        service_id=w.service_id,
        window_starts_at=w.window_starts_at,
        window_ends_at=w.window_ends_at,
        client_name=w.client_name,
        client_phone=w.client_phone,
        client_email=w.client_email,
        notes=w.notes,
        terms_accepted_at=w.terms_accepted_at,
        created_at=w.created_at,
    )
