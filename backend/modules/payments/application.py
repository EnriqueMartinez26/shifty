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
from typing import NamedTuple

from core.exceptions import (
    AppException,
    AppointmentNotFoundException,
    ValidationException,
)
from core.uow import AbstractUnitOfWork
from core.utils import ensure_utc_aware, now_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.notifications.tasks import EVENT_APPOINTMENT_CONFIRMED
from modules.payments.model import (
    PAYMENT_PROVIDER_MANUAL,
    AppointmentBalancePayment,
    BalancePaymentMethod,
    Payment,
    PaymentStatus,
)
from modules.payments.service import (
    EVENT_PREFERENCE_EXPIRE,
    RELEASED_APPOINTMENT_STATUSES,
    AppointmentNotPayableError,
    _is_placeholder_preference,
    calculate_service_payment_amount,
    ensure_payment_preference,
    lock_appointment_status,
    sync_appointment_with_payment,
)
from modules.services.model import Service
from modules.users.model import User

_ACCREDITED = {PaymentStatus.APPROVED.value, PaymentStatus.MANUAL_CONFIRMED.value}


def _manual_amount(
    appointment: Appointment, service: Service, amount: Decimal | None
) -> Decimal:
    """El importe pedido; si no, el precio congelado del turno; si no, el
    calculo por servicio (turnos historicos)."""
    if amount is not None:
        return amount
    if appointment.price_amount is not None:
        return appointment.price_amount
    return calculate_service_payment_amount(service) or Decimal(str(service.price))


class _ImportesARegistrar(NamedTuple):
    """Los importes con los que ``manual_confirm`` registra el cobro."""

    amount: Decimal
    original_amount: Decimal | None
    discount_amount: Decimal | None
    promotion_code: str | None


def _importes_a_registrar(
    actual: Payment | None,
    appointment: Appointment,
    service: Service,
    amount: Decimal | None,
) -> _ImportesARegistrar:
    """Sin importe, un cobro VIVO se registra por SU importe, venga de donde
    venga (link del panel, sena por MP o por WhatsApp): es el que mostro la
    pantalla. Antes solo se conservaba con ``deposit_rule`` y un link del
    panel se re-tarifaba al precio del turno (PR #131, C1, 2026-10-08). Promo
    y descuento se reescriben con los suyos, como la fase 2 del link del
    panel. Si no, ``_manual_amount``."""
    if amount is None and actual is not None and actual.is_live_charge:
        return _ImportesARegistrar(
            actual.amount,
            actual.original_amount,
            actual.discount_amount,
            actual.promotion_code,
        )
    return _ImportesARegistrar(
        _manual_amount(appointment, service, amount), None, None, None
    )


class AppointmentHoldExpiredError(AppException):
    """409 al confirmar a mano un turno que ya vencio (revision 4R de la PR
    #108): el personal tiene que saber por que no se puede y como seguir. El
    caso tipico es la sena por WhatsApp que entro despues del plazo: el job
    libero el horario y otra persona pudo tomarlo, asi que el turno no revive
    (regla 3); se agenda uno nuevo desde el panel y el pago se registra ahi.
    """

    def __init__(self) -> None:
        super().__init__(
            message=(
                "Este turno ya se liberó: venció el plazo para pagar la seña "
                "(o se liberó desde el panel) y el horario quedó libre. Si el "
                "cliente ya pagó, agendale un turno nuevo desde la agenda y "
                "registrá el pago en ese turno."
            ),
            http_status=409,
            error_code="APPOINTMENT_HOLD_EXPIRED",
        )


def _not_payable(estado: str | None) -> AppException:
    """El 409 de un turno soltado: el vencido dice como recuperarlo."""
    if estado == AppointmentStatus.EXPIRED.value:
        return AppointmentHoldExpiredError()
    return AppointmentNotPayableError()


class _ConflictoDelResto(AppException):
    """409 del saldo restante (D-20261008-01): mensaje fijo, sin datos del
    turno ni importes (regla 20)."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message=message, http_status=409, error_code=error_code)


def _sin_cobro_acreditado() -> AppException:
    return _ConflictoDelResto(
        "Este turno no tiene un pago acreditado: registrá el pago con "
        '"Confirmar pago".',
        "NO_ACCREDITED_PAYMENT",
    )


def _sin_saldo() -> AppException:
    return _ConflictoDelResto(
        "Este turno no tiene saldo pendiente.", "NO_REMAINING_BALANCE"
    )


def _resto_ya_registrado() -> AppException:
    return _ConflictoDelResto(
        "El resto de este turno ya está registrado. Si hubo un error, un "
        "administrador puede revertirlo y volver a cargarlo.",
        "REMAINING_PAYMENT_ALREADY_RECORDED",
    )


def _resto_excede_el_saldo() -> AppException:
    return _ConflictoDelResto(
        "El importe supera el saldo pendiente del turno.",
        "REMAINING_PAYMENT_EXCEEDS_BALANCE",
    )


def _sin_resto() -> AppException:
    return _ConflictoDelResto(
        "Este turno no tiene un resto registrado para revertir.",
        "NO_REMAINING_PAYMENT",
    )


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

        Un cobro ya acreditado (``approved``/``manual_confirmed``) es un no-op:
        se devuelve tal cual (revision de e5579b6..3b977a9, #5).

        Revision de perf/f4-pay (2026-09-25): lockea el turno PRIMERO (orden
        turno -> pago, regla 7), lo relee bajo el lock y rechaza un turno
        soltado sin tocar el cobro (``_lock_for_manual_confirm``). Un
        ``completed`` o ``absent`` se sigue cobrando a mano (el efectivo se
        registra despues de atender).

        Cierra la sena por WhatsApp sin MP ni flag ``payments`` (decision de
        Mateo, 2026-10-03): un cobro que nace aca (el turno no tenia uno) es
        de proveedor ``manual``, y si esta confirmacion confirma el turno, el
        cliente recibe "turno confirmado" (``_publish_confirmed_mail``).
        """
        actual = await self._lock_for_manual_confirm(appointment, actor)
        if actual is not None and actual.is_accredited:
            # Ya entro la plata: no-op 200 con el cobro tal como se acredito,
            # sin re-tarifar aunque el pedido traiga importe (decision del
            # dueno, revision de e5579b6..3b977a9, #5; antes 409). El commit
            # solo suelta los locks: no hay nada escrito.
            await self.uow.commit()
            return actual
        importes = _importes_a_registrar(actual, appointment, service, amount)
        payment = await ensure_payment_preference(
            self.uow.session,
            appointment=appointment,
            service=service,
            store_id=actor.store_id,
            amount_override=importes.amount,
            original_amount=importes.original_amount,
            discount_amount=importes.discount_amount,
            promotion_code=importes.promotion_code,
            create_provider_link=False,
            keep_existing_amount=amount is None,
            provider=PAYMENT_PROVIDER_MANUAL,
        )
        ya_confirmado = payment.status == PaymentStatus.MANUAL_CONFIRMED.value
        aplicada = payment.apply_status(
            PaymentStatus.MANUAL_CONFIRMED.value,
            payload={"notes": notes} if notes else None,
        )
        estado_previo = appointment.status
        sync_appointment_with_payment(appointment, payment.status)
        self._publish_confirmed_mail(appointment, estado_previo)
        # Sin evento payment.manual_confirmed: no tenia consumidor y se
        # republicaba en cada doble clic (B2-17, 2026-09-19). El vencimiento
        # del link sale una sola vez, con la primera confirmacion real.
        if aplicada and not ya_confirmado:
            self._expire_live_checkout(payment)
        await self.uow.commit()
        return payment

    async def record_remaining_payment(
        self,
        *,
        appointment: Appointment,
        actor: User,
        amount: Decimal | None,
        method: BalancePaymentMethod | None,
    ) -> tuple[AppointmentBalancePayment, Decimal]:
        """Registra el resto del turno pagado aparte de su cobro.

        Saldo restante por turno, opcion A (D-20261008-01): el cobro
        acreditado (una sena de $960) puede ser menor que el precio congelado
        ($3.200); el resto ($2.240) se paga en el local. Lockea el turno y
        despues su cobro (regla 7, ``_lock_for_manual_confirm``: un turno
        soltado es 409 como la confirmacion manual) y relee el saldo en SQL
        bajo esos locks: dos registros a la vez se serializan y el segundo ve
        el primero (409). Sin ``amount`` registra el saldo entero.

        Devuelve el resto y el saldo que queda.
        """
        cobro = await self._lock_for_manual_confirm(appointment, actor)
        if cobro is None or not cobro.is_accredited:
            raise _sin_cobro_acreditado()
        restos = self.uow.balance_payments
        if await restos.get_live(appointment.id, actor.store_id) is not None:
            raise _resto_ya_registrado()
        saldo = await restos.remaining_balance(appointment.id, actor.store_id)
        if saldo <= 0:
            raise _sin_saldo()
        importe = saldo if amount is None else amount
        if importe > saldo:
            raise _resto_excede_el_saldo()
        resto = AppointmentBalancePayment(
            store_id=actor.store_id,
            appointment_id=appointment.id,
            amount=importe,
            method=method.value if method is not None else None,
            recorded_by=actor.id,
        )
        restos.add(resto)
        await self.uow.session.flush()
        queda = await restos.remaining_balance(appointment.id, actor.store_id)
        await self.uow.commit()
        return resto, queda

    async def revert_remaining_payment(
        self, *, appointment: Appointment, actor: User
    ) -> tuple[AppointmentBalancePayment, Decimal]:
        """Marca revertido el resto vivo del turno (D-20261008-01).

        La devolucion se hace fuera del sistema: aca solo se marca, la fila
        queda como auditoria y el saldo vuelve. Vale en cualquier estado del
        turno (corrige un registro equivocado). Lockea el turno y despues el
        resto (regla 7); el cobro no se toca. Devuelve el resto y el saldo.
        """
        estado = await lock_appointment_status(
            self.uow.session, appointment_id=appointment.id, store_id=actor.store_id
        )
        if estado is None:
            raise AppointmentNotFoundException(public_id=appointment.public_id)
        restos = self.uow.balance_payments
        resto = await restos.get_live(appointment.id, actor.store_id, lock=True)
        if resto is None:
            raise _sin_resto()
        resto.revert(actor_id=actor.id)
        await self.uow.session.flush()
        saldo = await restos.remaining_balance(appointment.id, actor.store_id)
        await self.uow.commit()
        return resto, saldo

    async def _lock_for_manual_confirm(
        self, appointment: Appointment, actor: User
    ) -> Payment | None:
        """Turno lockeado y releido, y despues su cobro lockeado (regla 7).

        Un turno soltado no se cobra: ``cancelled`` es 409
        ``APPOINTMENT_NOT_PAYABLE`` y ``expired`` es 409
        ``APPOINTMENT_HOLD_EXPIRED``, que le dice al personal como seguir
        (``AppointmentHoldExpiredError``).
        """
        estado = await lock_appointment_status(
            self.uow.session, appointment_id=appointment.id, store_id=actor.store_id
        )
        if estado is None or estado in RELEASED_APPOINTMENT_STATUSES:
            raise _not_payable(estado)
        # El router lo leyo sin lock: se relee con la fila ya lockeada.
        await self.uow.session.refresh(appointment)
        return await self.uow.payments.get_by_appointment_locked(
            appointment.id, actor.store_id
        )

    def _publish_confirmed_mail(
        self, appointment: Appointment, estado_previo: str
    ) -> None:
        """Mail "turno confirmado" al cliente por el outbox, en la transaccion
        de la confirmacion (F2-02), como ``AppointmentService.confirm``.

        Solo si ESTA confirmacion confirmo el turno (un doble clic o el
        efectivo de un turno ya confirmado no lo repiten) y si el turno no
        empezo: un turno pasado lo registra la tienda (un walk-in, D-20260925-01)
        y no lleva aviso al cliente, que ya estuvo.
        """
        confirmado = AppointmentStatus.CONFIRMED.value
        if estado_previo == confirmado or appointment.status != confirmado:
            return
        if ensure_utc_aware(appointment.starts_at) < now_utc():
            return
        self.uow.outbox.publish(
            store_id=appointment.store_id,
            event_type=EVENT_APPOINTMENT_CONFIRMED,
            payload={"appointment_id": appointment.id},
        )

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

        B2-05 (2026-09-18, decision de Mateo): Shifty no mueve plata en
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
