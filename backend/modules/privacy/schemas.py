"""Exportacion de los datos de un cliente (derecho de acceso, art. 14 Ley 25.326)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class ExportedClient(BaseModel):
    public_id: str
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool
    created_at: datetime | None = None


class ExportedAppointment(BaseModel):
    public_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    service_id: str
    staff_id: str
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    notes: str | None = None
    notes_staff: str | None = None
    intake_answers: dict[str, Any] | None = None
    price_amount: Decimal | None = None
    terms_accepted_at: datetime | None = None
    terms_version: str | None = None
    privacy_version: str | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None


class ExportedPayment(BaseModel):
    public_id: str
    appointment_id: str
    provider: str
    amount: Decimal
    currency: str
    status: str
    paid_at: datetime | None = None
    created_at: datetime | None = None


class ExportedLedgerMovement(BaseModel):
    public_id: str
    movement_type: str
    amount: Decimal
    balance_after: Decimal
    appointment_id: str | None = None
    notes: str | None = None
    created_at: datetime | None = None


class ExportedWaitlistEntry(BaseModel):
    public_id: str
    status: str
    service_id: str
    window_starts_at: datetime
    window_ends_at: datetime
    client_name: str
    client_phone: str
    client_email: str | None = None
    notes: str | None = None
    terms_accepted_at: datetime | None = None
    created_at: datetime | None = None


class ClientDataExport(BaseModel):
    """Todo lo que la tienda guarda del cliente, en JSON. No incluye lo que
    se purga solo (OTP, avisos, cola de mails) ni la auditoria."""

    exported_at: datetime
    store_id: str
    client: ExportedClient
    appointments: list[ExportedAppointment]
    payments: list[ExportedPayment]
    ledger: list[ExportedLedgerMovement]
    waitlist: list[ExportedWaitlistEntry]


class AnonymizeResponse(BaseModel):
    status: str
