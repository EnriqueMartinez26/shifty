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
from modules.notifications.model import NotificationType
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

        Un cobro que nacio con la regla de sena (snapshot ``deposit_rule``) NO
        se re-tarifa: registrarlo a mano pasaba su importe de la sena al total,
        borraba ``promotion_code``, dejaba el snapshot mintiendo y pisaba el
        ``preference_id`` real con el placeholder, dejando vivo en Mercado Pago
        un checkout que Shifty ya no podia reconocer (AUD2-B2-01, 2026-09-19).
        El ``amount`` explicito del pedido es el unico que re-tarifa.
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
            keep_existing_amount=amount is None,
        )
        payment.apply_status(
            PaymentStatus.MANUAL_CONFIRMED.value,
            payload={"notes": notes} if notes else None,
        )
        sync_appointment_with_payment(appointment, payment.status)
        # Sin evento de outbox: payment.manual_confirmed no tenia consumidor y
        # se republicaba en cada doble clic (B2-17, 2026-09-19).
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
        """REGISTRA un reembolso hecho fuera de Shifty. No pisa el monto historico.

        B2-05 (2026-09-18, decision del dueno): Shifty no mueve plata en
        Mercado Pago. Antes, con ``manual`` ausente o ``false``, el cobro
        quedaba ``refunded`` y la conciliacion lo contaba como devuelto
        mientras la plata seguia en la cuenta de MP de la tienda. Ahora solo
        se acepta el registro explicito (``manual=True``) de un reembolso que
        el dueno ya hizo por su cuenta; un reembolso automatico real es
        irreversible y necesita compensacion probada (regla 5), no es esta
        pasada. No se llama a Mercado Pago en ningun caso.
        """
        if not manual:
            raise ValidationException(
                "Shifty solo registra reembolsos hechos fuera de Shifty: hace la "
                "devolucion desde Mercado Pago (o en efectivo) y registrala con "
                "manual=true"
            )
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
        # Consumidor: aviso "Reembolso registrado" en el panel (B2-17).
        self.uow.outbox.publish(
            store_id=actor.store_id,
            event_type=NotificationType.PAYMENT_REFUNDED.value,
            payload={
                "payment_id": payment.id,
                "appointment_id": payment.appointment_id,
                "amount": str(refund_amount),
                "reason": reason,
            },
        )
        await self.uow.commit()
        return payment
