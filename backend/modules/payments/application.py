"""Casos de uso transaccionales de pagos (capa de aplicacion).

Antes estas reglas (confirmar un cobro manual, reembolsar) vivian en los
handlers HTTP de ``payments/router.py``, que ademas hacian el commit. Este
service las concentra sobre el Unit of Work, al mismo nivel que
``AppointmentService``: el router queda fino (carga, delega, responde) y la
logica se puede testear sin HTTP.

Las funciones de gateway de Mercado Pago siguen en ``payments/service.py`` (son
adaptadores de infraestructura que ya importan muchos modulos); aca solo se
orquesta el caso de uso.
"""

from __future__ import annotations

from decimal import Decimal

from core.exceptions import ValidationException
from core.uow import AbstractUnitOfWork
from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from modules.payments.service import (
    calculate_service_payment_amount,
    ensure_payment_preference,
    sync_appointment_with_payment,
)
from modules.services.model import Service
from modules.users.model import User

_ACCREDITED = {PaymentStatus.APPROVED.value, PaymentStatus.MANUAL_CONFIRMED.value}


class PaymentService:
    def __init__(self, uow: AbstractUnitOfWork) -> None:
        self.uow = uow

    async def manual_confirm(
        self,
        *,
        appointment: Appointment,
        service: Service,
        actor: User,
        amount: Decimal | None = None,
        notes: str | None = None,
    ) -> Payment:
        """Registra un cobro hecho fuera del sistema (efectivo/WhatsApp).

        El monto por defecto es el precio congelado del turno (no el de lista de
        hoy); recien despues cae al calculo por servicio para turnos historicos.
        """
        resolved = amount
        if resolved is None and appointment.price_amount is not None:
            resolved = appointment.price_amount
        if resolved is None:
            resolved = calculate_service_payment_amount(service) or Decimal(
                str(service.price)
            )

        payment = await ensure_payment_preference(
            self.uow.session,
            appointment=appointment,
            service=service,
            store_id=actor.store_id,
            amount_override=resolved,
            create_provider_link=False,
        )
        payment.apply_status(
            PaymentStatus.MANUAL_CONFIRMED.value,
            payload={"notes": notes} if notes else None,
        )
        sync_appointment_with_payment(appointment, payment.status)
        self.uow.outbox.publish(
            store_id=actor.store_id,
            event_type="payment.manual_confirmed",
            payload={"appointment_id": appointment.id, "payment_id": payment.id},
        )
        await self.uow.commit()
        return payment

    async def refund(
        self,
        *,
        payment: Payment,
        actor: User,
        amount: Decimal | None = None,
        reason: str | None = None,
        manual: bool = False,
    ) -> Payment:
        """Reembolsa un pago acreditado. No pisa el monto historico del cobro."""
        # Solo se puede devolver plata que efectivamente entro.
        if payment.status not in _ACCREDITED:
            raise ValidationException(
                "Solo se pueden reembolsar pagos acreditados o confirmados manualmente"
            )
        refund_amount = amount if amount is not None else payment.amount
        if refund_amount <= 0 or refund_amount > payment.amount:
            raise ValidationException(
                "El importe a reembolsar debe ser mayor a cero y no superar lo cobrado"
            )
        payment.apply_status(
            PaymentStatus.REFUNDED.value,
            payload={
                "reason": reason,
                "manual": manual,
                "refunded_amount": str(refund_amount),
            },
        )
        appointment = await self.uow.appointments.get_by_public_id(
            payment.appointment_id, actor.store_id
        )
        if appointment:
            sync_appointment_with_payment(appointment, payment.status)
        self.uow.outbox.publish(
            store_id=actor.store_id,
            event_type="payment.refunded",
            payload={"payment_id": payment.id, "reason": reason},
        )
        await self.uow.commit()
        return payment
