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
    EVENT_PREFERENCE_EXPIRE,
    AppointmentNotPayableError,
    _is_placeholder_preference,
    calculate_service_payment_amount,
    ensure_payment_preference,
    lock_payable_appointment,
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

        El link real que se conserva se manda a vencer en Mercado Pago
        (``_expire_live_checkout``): la plata ya entro por otro lado.

        Revision de perf/f4-pay (2026-09-25): lockea el turno PRIMERO (orden
        turno -> pago, regla 7), lo relee bajo el lock y rechaza un turno
        soltado (``cancelled``/``expired``, p. ej. recien cancelado por el
        personal) con 409 ``APPOINTMENT_NOT_PAYABLE`` sin tocar el cobro. Un
        ``completed`` o ``absent`` se sigue cobrando a mano (el efectivo se
        registra despues de atender).
        """
        if not await lock_payable_appointment(
            self.uow.session, appointment_id=appointment.id, store_id=actor.store_id
        ):
            raise AppointmentNotPayableError()
        # El router lo leyo sin lock: se relee con la fila ya lockeada.
        await self.uow.session.refresh(appointment)
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
        ya_confirmado = payment.status == PaymentStatus.MANUAL_CONFIRMED.value
        aplicada = payment.apply_status(
            PaymentStatus.MANUAL_CONFIRMED.value,
            payload={"notes": notes} if notes else None,
        )
        sync_appointment_with_payment(appointment, payment.status)
        # Sin evento payment.manual_confirmed: no tenia consumidor y se
        # republicaba en cada doble clic (B2-17, 2026-09-19). El vencimiento
        # del link sale una sola vez, con la primera confirmacion real.
        if aplicada and not ya_confirmado:
            self._expire_live_checkout(payment)
        await self.uow.commit()
        return payment

    def _expire_live_checkout(self, payment: Payment) -> None:
        """Manda a vencer en MP el link real del cobro recien confirmado a mano.

        V-diff de AUD2-B2-01 (2026-09-20): conservar el ``preference_id`` no
        alcanzaba. AUD2-B2-03 solo vence la preferencia cuando el id CAMBIA,
        asi que el checkout seguia vivo; si el cliente pagaba ese link,
        ``find_payment_for_webhook`` lo encontraba, la integridad pasaba (mismo
        importe, misma preferencia), ``approved`` desde ``manual_confirmed`` se
        ignoraba por ilegal, ``was_settled`` tapaba el aviso y el inbox se
        sellaba: plata en Mercado Pago sin ninguna senal (antes al menos caia
        en ``failed_webhooks``).

        El id se conserva en la fila para trazabilidad; lo que se vence es el
        checkout, y fuera de esta transaccion: lo consume
        ``_claim_and_expire_preferences`` (B1-04, regla 5). Un placeholder no
        existe en Mercado Pago, asi que no se publica nada.
        """
        if _is_placeholder_preference(payment.preference_id):
            return
        self.uow.outbox.publish(
            store_id=payment.store_id,
            event_type=EVENT_PREFERENCE_EXPIRE,
            payload={
                "appointment_id": payment.appointment_id,
                "payment_id": payment.id,
                "preference_id": payment.preference_id,
            },
        )

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
