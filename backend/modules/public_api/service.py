"""
Servicio del portal publico: dueno de la transaccion de la reserva (B1-12).

Hasta el 2026-09-19 todo esto vivia en ``create_public_booking`` (371 lineas
en el router, con sus commits). Se movio aca con el patron de
``appointments``: el router hace HTTP (rate limit, bypass de tenant,
idempotencia) y el service orquesta la transaccion. El orden de las guardas
es el mismo de antes y lo fijan los tests de caracterizacion
(``tests/integration/test_caracterizacion_alta_publica.py``):

- rechazos (tienda suspendida, antelacion, OTP, campos, promo) antes de
  escribir nada;
- el lock del profesional se toma dentro del savepoint del alta, antes de
  leer disponibilidad (``PublicRepository.create_appointment``, regla 4);
- commit del alta -> invalidacion del cache -> link de Mercado Pago fuera de
  la transaccion -> compensacion si falla (regla 5, B1-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from fastapi import status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import invalidate_availability
from core.circuit_breaker import CircuitBreakerOpenError
from core.config import settings
from core.exceptions import (
    AppException,
    BookingNoticeException,
    OTPException,
    ServiceNotFoundException,
    StoreNotFoundException,
    ValidationException,
)
from core.feature_flags import is_store_feature_enabled
from modules.appointments.model import Appointment, AppointmentStatus
from modules.billing.dependencies import reject_new_public_business_when_suspended
from modules.notifications.model import NotificationType
from modules.notifications.tasks import (
    build_client_details,
    send_confirmation_email,
    send_registration_email,
)
from modules.otp.service import OtpService
from modules.payments.deposit_rules import (
    UNKNOWN_HISTORY,
    ClientHistory,
    DepositDecision,
    DepositRules,
    decide_deposit,
)
from modules.payments.model import OutboxMessage, Payment
from modules.payments.service import ensure_payment_preference
from modules.promotions.model import PromotionRedemption
from modules.promotions.service import PromotionQuote, quote_promotion, redeem_promotion
from modules.public_api.repository import PublicRepository
from modules.public_api.schemas import PublicBookingCreate, PublicBookingResponse
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.waitlist.offers import mark_booked

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Reglas puras (antes en el router)
# ---------------------------------------------------------------------------


def payment_hold_deadline(starts_at: datetime) -> datetime:
    """Hasta cuando se retiene el slot de un turno que espera el pago de la seña.

    Nunca mas alla del horario del turno. Devuelve el valor con la misma
    conciencia de zona horaria que ``starts_at`` para no mezclar naive y aware.
    """
    is_naive = starts_at.tzinfo is None
    reference = starts_at.replace(tzinfo=timezone.utc) if is_naive else starts_at
    deadline = min(
        datetime.now(timezone.utc) + timedelta(minutes=settings.PAYMENT_HOLD_MINUTES),
        reference,
    )
    return deadline.replace(tzinfo=None) if is_naive else deadline


def _normalize_custom_field_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def validate_custom_fields(
    store: Store, custom_fields: dict[str, str] | None
) -> dict[str, str]:
    configured_fields = store.custom_client_fields or []
    configured_by_key = {
        field.get("key"): field
        for field in configured_fields
        if isinstance(field, dict) and field.get("key")
    }
    incoming = custom_fields or {}

    unknown_keys = [key for key in incoming if key not in configured_by_key]
    if unknown_keys:
        raise ValidationException(
            message=f"Campos extra invalidos: {', '.join(sorted(unknown_keys))}"
        )

    normalized: dict[str, str] = {}
    for key, raw_value in incoming.items():
        value = _normalize_custom_field_value(raw_value)
        if len(value) > 500:
            raise ValidationException(
                message=f"El campo extra '{key}' supera el maximo permitido"
            )

        field_config = configured_by_key[key]
        if field_config.get("type") == "select" and value:
            allowed_values = {
                str(option.get("value", "")).strip()
                for option in (field_config.get("options") or [])
                if isinstance(option, dict)
            }
            if allowed_values and value not in allowed_values:
                raise ValidationException(
                    message=f"Valor invalido para el campo '{field_config.get('label') or key}'"
                )
        normalized[key] = value

    missing_required = [
        str(field.get("label") or field.get("key") or "")
        for field in configured_fields
        if field.get("required")
        and not normalized.get(field.get("key", ""), "").strip()
    ]
    if missing_required:
        raise ValidationException(
            message=f"Faltan campos requeridos: {', '.join(missing_required)}"
        )

    return {key: value for key, value in normalized.items() if value}


def resolve_payment_requirement(
    payment_method: str,
    payments_enabled: bool,
    deposit_amount: Decimal,
    deposit_mode: str,
    allow_manual_coordination: bool,
) -> bool:
    # Responde una sola vez "con el metodo pedido y estos datos de tienda/
    # servicio, hace falta pagar la sena para reservar" en vez de repetir la
    # misma combinacion de 5 variables en tres ifs distintos. Puede levantar
    # ValidationException si el payment_method pedido no es viable.
    viable = payments_enabled and deposit_amount > 0
    mandatory_online = (
        viable and deposit_mode == "required" and not allow_manual_coordination
    )

    if payment_method == "mercadopago":
        if deposit_amount <= 0:
            raise ValidationException(
                "Este servicio no tiene una seña configurada para Mercado Pago"
            )
        if not payments_enabled:
            raise ValidationException(
                "La tienda no tiene habilitados los cobros con Mercado Pago"
            )
        return True
    if payment_method == "manual":
        if mandatory_online:
            raise ValidationException(
                "Este servicio requiere pagar la seña con Mercado Pago para reservar"
            )
        return False
    return viable  # "auto"


def decide(
    service: Service,
    store: Store,
    *,
    price: Decimal,
    starts_at: datetime,
    history: ClientHistory,
    now: datetime | None = None,
) -> DepositDecision:
    now = now or datetime.now(timezone.utc)
    return decide_deposit(
        service,
        price=price,
        notice=starts_at - now,
        rules=DepositRules.from_store(store),
        history=history,
    )


async def revert_failed_booking(
    db: AsyncSession, redis: Redis, appointment: Appointment
) -> None:
    """Compensa un booking cuyo link de pago fallo DESPUES del commit.

    Como el link de Mercado Pago se genera fuera de la transaccion que sostiene
    el lock (fix del DoS), el turno + Payment ya estan persistidos cuando MP
    falla. Se revierten para no dejar el slot retenido ni un pago sin link, y
    para que un reintento pueda crear el turno limpio. Reemplaza al rollback del
    savepoint que existia cuando el HTTP corria dentro de la transaccion.

    La agenda vuelve atras, asi que se invalida la disponibilidad (B1-10):
    sin eso, quien la hubiera leido entre el commit y la compensacion dejaba
    el slot cacheado como ocupado hasta que vencia el TTL.
    """
    appointment_id = appointment.id
    store_id = appointment.store_id
    starts_at = appointment.starts_at
    await db.execute(
        delete(PromotionRedemption).where(
            PromotionRedemption.appointment_id == appointment_id
        )
    )
    await db.execute(delete(Payment).where(Payment.appointment_id == appointment_id))
    await db.execute(delete(Appointment).where(Appointment.id == appointment_id))
    await db.commit()
    # Best-effort: la compensacion en base ya quedo commiteada. Un Redis caido
    # aca no puede tapar el 502/503 del llamador ni saltear la liberacion de
    # la idempotencia; en el peor caso el slot se ve ocupado hasta el TTL.
    try:
        await invalidate_availability(redis, store_id, starts_at)
    except RedisError as exc:
        logger.warning(
            "revert_booking_cache_invalidation_failed",
            appointment_id=appointment_id,
            error_type=type(exc).__name__,
        )


def _payment_provider_unavailable(exc: Exception) -> AppException:
    return AppException(
        message=f"Proveedor de pagos temporalmente no disponible: {exc}",
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="PAYMENT_PROVIDER_UNAVAILABLE",
    )


def _payment_link_failed(exc: Exception) -> AppException:
    return AppException(
        message=f"No se pudo iniciar el cobro online: {exc}",
        http_status=status.HTTP_502_BAD_GATEWAY,
        error_code="PAYMENT_LINK_CREATION_FAILED",
    )


# ---------------------------------------------------------------------------
# Alta publica
# ---------------------------------------------------------------------------


@dataclass
class _BookingRequest:
    """Todo lo que se resuelve ANTES de escribir (sin locks tomados)."""

    store: Store
    store_id: str
    service: Service
    starts_at_utc: datetime
    phone_verified: bool
    custom_fields: dict[str, str]
    base_price: Decimal
    discounted_price: Decimal
    history: ClientHistory
    deposit: DepositDecision
    payment_required: bool


@dataclass
class _Booking:
    """Lo que dejo escrito el savepoint del alta."""

    appointment: Appointment
    service: Service
    staff: Staff
    payment: Payment | None
    promotion_quote: PromotionQuote | None


class PublicBookingService:
    """Casos de uso del portal que escriben. Se instancia por request."""

    def __init__(self, db: AsyncSession, cache: Redis) -> None:
        self.db = db
        self.cache = cache
        self.repo = PublicRepository(db)

    async def book(
        self, data: PublicBookingCreate, idempotency_key: str
    ) -> PublicBookingResponse:
        """Reserva desde el portal. El llamador maneja la idempotencia.

        Commit del alta -> invalidacion -> link de MP (fuera de la
        transaccion, con compensacion) -> mail -> respuesta -> cierre de la
        entrada de lista de espera (best-effort).
        """
        service, store = await self._resolve_store_and_service(data)
        request = await self._resolve_request(data, service, store)
        booking = await self._persist(data, request, idempotency_key)

        await self.db.commit()
        # El cupo dejo de estar libre: la disponibilidad publica lo refleja ya
        # (antes la reserva publica no invalidaba nada y el slot seguia
        # "available" hasta cinco minutos).
        await invalidate_availability(
            self.cache, request.store_id, booking.appointment.starts_at
        )
        await self._attach_payment_link(request, booking)
        await self._notify_client(request, booking)
        response = _booking_response(data, request, booking)
        await self._close_waitlist_entry(data, request, booking)
        return response

    async def _resolve_store_and_service(
        self, data: PublicBookingCreate
    ) -> tuple[Service, Store]:
        service = await self.repo.get_service_by_public_id(data.service_id)
        if not service:
            raise ServiceNotFoundException(identifier=data.service_id)

        if data.store_public_id:
            store = await self.repo.get_store_by_public_id(data.store_public_id)
            if not store:
                raise StoreNotFoundException(identifier=data.store_public_id)
            if service.store_id != store.id:
                raise ServiceNotFoundException(identifier=data.service_id)
        else:
            store = await self.repo.get_store_by_id(service.store_id)
            if not store:
                raise StoreNotFoundException(identifier=str(service.store_id))
        # Tienda suspendida: no toma reservas nuevas (B1-06); cancelar y
        # reprogramar las ya tomadas sigue.
        await reject_new_public_business_when_suspended(self.db, store)
        return service, store

    async def _resolve_request(
        self, data: PublicBookingCreate, service: Service, store: Store
    ) -> _BookingRequest:
        """Antelacion, OTP, campos extra, precio y sena: todo antes de escribir."""
        # Antelacion minima. El flujo admin ya la validaba, pero el booking
        # publico solo la aplicaba al *mostrar* slots, no al crearlos: un POST
        # directo podia agendar en el pasado o dentro de la ventana bloqueada.
        notice_hours = getattr(store, "min_booking_notice_hours", 2) or 0
        starts_at_utc = (
            data.starts_at
            if data.starts_at.tzinfo
            else data.starts_at.replace(tzinfo=timezone.utc)
        )
        if starts_at_utc < datetime.now(timezone.utc) + timedelta(hours=notice_hours):
            raise BookingNoticeException(notice_hours)

        # El OTP es lo unico que prueba que quien reserva es dueno del
        # telefono: sin el, los datos de contacto de esta peticion no pisan
        # los del cliente que ya existe (ver get_or_create_client).
        phone_verified = await OtpService(self.db).is_recently_verified(
            store_id=store.id,
            phone=data.client_phone,
        )
        if is_store_feature_enabled(store.feature_flags, "otp_booking"):
            if not phone_verified:
                raise OTPException(
                    message="Se requiere validar OTP antes de reservar",
                    error_code="OTP_VERIFICATION_REQUIRED",
                    http_status=status.HTTP_403_FORBIDDEN,
                )

        custom_fields = validate_custom_fields(store, data.custom_fields)
        base_price = Decimal(str(service.price or 0))
        discounted_price = await self._discounted_price(
            data, service, store, base_price
        )
        return self._decide_deposit(
            data,
            store=store,
            service=service,
            starts_at_utc=starts_at_utc,
            phone_verified=phone_verified,
            custom_fields=custom_fields,
            base_price=base_price,
            discounted_price=discounted_price,
            history=(
                # Mismo criterio que el preview: un telefono sin verificar no
                # trae el historial de nadie, ni para mostrar ni para cobrar.
                # Si no, quien tipea el telefono de otro hereda (o le carga)
                # sus recargos. Una sola consulta agregada, antes del lock.
                await self.repo.get_client_history(store.id, data.client_phone)
                if phone_verified
                else UNKNOWN_HISTORY
            ),
        )

    async def _discounted_price(
        self,
        data: PublicBookingCreate,
        service: Service,
        store: Store,
        base_price: Decimal,
    ) -> Decimal:
        if not data.promotion_code:
            return base_price
        _promotion, preview_quote, preview_error = await quote_promotion(
            self.db,
            store_id=store.id,
            service=service,
            code=data.promotion_code,
        )
        if not preview_quote:
            raise ValidationException(preview_error or "Promocion invalida")
        return preview_quote.final_amount

    @staticmethod
    def _decide_deposit(
        data: PublicBookingCreate,
        *,
        store: Store,
        service: Service,
        starts_at_utc: datetime,
        phone_verified: bool,
        custom_fields: dict[str, str],
        base_price: Decimal,
        discounted_price: Decimal,
        history: ClientHistory,
    ) -> _BookingRequest:
        # La regla de sena se evalua UNA vez (misma antelacion, mismo
        # historial) y el resultado viaja hasta el pago y la respuesta. Antes
        # se recalculaba tres veces con `now` distinto.
        deposit = decide(
            service,
            store,
            price=discounted_price,
            starts_at=starts_at_utc,
            history=history,
        )
        payment_required = resolve_payment_requirement(
            payment_method=data.payment_method,
            payments_enabled=is_store_feature_enabled(store.feature_flags, "payments"),
            deposit_amount=deposit.amount,
            deposit_mode=getattr(service, "deposit_mode", "none") or "none",
            allow_manual_coordination=store.allow_manual_coordination,
        )
        return _BookingRequest(
            store=store,
            store_id=store.id,
            service=service,
            starts_at_utc=starts_at_utc,
            phone_verified=phone_verified,
            custom_fields=custom_fields,
            base_price=base_price,
            discounted_price=discounted_price,
            history=history,
            deposit=deposit,
            payment_required=payment_required,
        )

    async def _persist(
        self,
        data: PublicBookingCreate,
        request: _BookingRequest,
        idempotency_key: str,
    ) -> _Booking:
        """Savepoint del alta; traduce los errores de dominio a HTTP."""
        try:
            async with self.db.begin_nested():
                return await self._write_booking(data, request, idempotency_key)
        except ValueError as exc:
            raise AppException(
                message=str(exc), http_status=409, error_code="APPOINTMENT_CONFLICT"
            )
        except CircuitBreakerOpenError as exc:
            raise _payment_provider_unavailable(exc)
        except RuntimeError as exc:
            raise _payment_link_failed(exc)

    async def _write_booking(
        self,
        data: PublicBookingCreate,
        request: _BookingRequest,
        idempotency_key: str,
    ) -> _Booking:
        store_id = request.store_id
        client = await self.repo.get_or_create_client(
            store_id=store_id,
            phone=data.client_phone,
            name=data.client_name,
            email=data.client_email,
            adopt_contact=request.phone_verified,
        )
        # Toma el FOR UPDATE del profesional antes de leer disponibilidad
        # (regla 4) y aplica el buffer de la tienda.
        appointment, service, staff = await self.repo.create_appointment(
            store_id=store_id,
            service_public_id=data.service_id,
            staff_public_id=data.staff_id,
            starts_at=data.starts_at,
            client=client,
            notes=data.notes,
            intake_answers=request.custom_fields,
            idempotency_key=idempotency_key,
            initial_status=(
                AppointmentStatus.PENDING_PAYMENT.value
                if request.payment_required
                else AppointmentStatus.PENDING.value
            ),
            buffer_minutes=request.store.buffer_minutes or 0,
            price_amount=request.discounted_price,
            client_email=str(data.client_email) if data.client_email else None,
        )
        # Un turno esperando la seña retiene el slot solo por una ventana
        # corta: si no se paga, vuelve a estar disponible enseguida en vez
        # de bloquear la agenda hasta la hora del turno. La coordinacion
        # manual si retiene hasta el horario, porque la confirma la tienda.
        if request.payment_required:
            appointment.expires_at = payment_hold_deadline(appointment.starts_at)
        else:
            appointment.expires_at = appointment.starts_at
        if data.accepts_terms:
            appointment.terms_accepted_at = datetime.now(timezone.utc)
        promotion_quote = None
        if data.promotion_code:
            try:
                promotion_quote = await redeem_promotion(
                    self.db,
                    store_id=store_id,
                    appointment_id=appointment.id,
                    client=client,
                    service=service,
                    code=data.promotion_code,
                )
            except ValueError as exc:
                raise ValidationException(str(exc))
        booking = _Booking(appointment, service, staff, None, promotion_quote)
        if request.payment_required:
            booking.payment = await self._create_pending_payment(request, booking)
        else:
            # El pago se coordina por fuera, asi que la tienda tiene que
            # confirmar el turno a mano cuando reciba la transferencia.
            self.db.add(
                OutboxMessage(
                    store_id=store_id,
                    event_type=NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
                    payload={
                        "appointment_id": appointment.id,
                        "client_name": data.client_name,
                        "service_name": service.name,
                    },
                )
            )
        return booking

    async def _create_pending_payment(
        self, request: _BookingRequest, booking: _Booking
    ) -> Payment:
        # Misma regla (antelacion e historial), dos precios: el de lista para
        # mostrar el descuento y el final para cobrar.
        service, quote = booking.service, booking.promotion_quote
        payable_before_discount = decide(
            service,
            request.store,
            price=request.base_price,
            starts_at=request.starts_at_utc,
            history=request.history,
        ).amount
        final_decision = (
            decide(
                service,
                request.store,
                price=quote.final_amount,
                starts_at=request.starts_at_utc,
                history=request.history,
            )
            if quote
            else request.deposit
        )
        payable_after_discount = final_decision.amount
        # Dentro de la transaccion (que sostiene el lock FOR UPDATE del staff)
        # solo se crea el Payment PENDING con link placeholder: la llamada HTTP
        # a Mercado Pago se hace DESPUES del commit, con el lock ya soltado,
        # para no serializar reservas ni agotar el pool ante latencia de MP.
        return await ensure_payment_preference(
            self.db,
            appointment=booking.appointment,
            service=service,
            store_id=request.store_id,
            amount_override=payable_after_discount,
            original_amount=payable_before_discount,
            discount_amount=max(
                Decimal("0.00"), payable_before_discount - payable_after_discount
            ),
            promotion_code=quote.code if quote else None,
            create_provider_link=False,
            deposit_rule=final_decision.snapshot(),
        )

    async def _attach_payment_link(
        self, request: _BookingRequest, booking: _Booking
    ) -> None:
        """Link real de MP, ya fuera de la transaccion y sin el lock (regla 5).

        Si MP falla se compensa: turno, pago y canje se borran y se invalida
        la disponibilidad (B1-10); el llamador libera la idempotencia.
        """
        payment = booking.payment
        if not request.payment_required or payment is None:
            return
        try:
            await ensure_payment_preference(
                self.db,
                appointment=booking.appointment,
                service=booking.service,
                store_id=request.store_id,
                amount_override=payment.amount,
                original_amount=payment.original_amount,
                discount_amount=payment.discount_amount,
                promotion_code=payment.promotion_code,
                create_provider_link=True,
            )
            await self.db.commit()
        except CircuitBreakerOpenError as exc:
            await revert_failed_booking(self.db, self.cache, booking.appointment)
            raise _payment_provider_unavailable(exc)
        except RuntimeError as exc:
            await revert_failed_booking(self.db, self.cache, booking.appointment)
            raise _payment_link_failed(exc)

    async def _notify_client(self, request: _BookingRequest, booking: _Booking) -> None:
        # Aviso al cliente por mail (best-effort, fuera de la transaccion).
        # Antes la condicion exigia CONFIRMED y el turno nace PENDING o
        # PENDING_PAYMENT: nunca salia nada. Ahora "reserva registrada" al
        # crear, y "turno confirmado" solo si ya nacio confirmado.
        appointment = booking.appointment
        details = build_client_details(
            appointment, booking.service, booking.staff, request.store
        )
        if appointment.status == AppointmentStatus.CONFIRMED.value:
            await send_confirmation_email(
                email=appointment.client_email, details=details
            )
        else:
            await send_registration_email(
                email=appointment.client_email, details=details
            )

    async def _close_waitlist_entry(
        self, data: PublicBookingCreate, request: _BookingRequest, booking: _Booking
    ) -> None:
        # Recien con el turno firme (incluido el link de pago) se cierra la
        # entrada de lista de espera: cerrarla antes la perdia si el link de
        # Mercado Pago fallaba y el turno se revertia. Best-effort: no puede
        # deshacer una reserva ya hecha.
        try:
            if await mark_booked(
                self.db,
                store_id=request.store_id,
                client_phone=data.client_phone,
                service_id=booking.service.id,
                starts_at=booking.appointment.starts_at,
            ):
                await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            logger.warning("waitlist_mark_booked_failed", error_type=type(exc).__name__)


def _booking_response(
    data: PublicBookingCreate, request: _BookingRequest, booking: _Booking
) -> PublicBookingResponse:
    appointment, payment = booking.appointment, booking.payment
    service, staff, quote = booking.service, booking.staff, booking.promotion_quote
    return PublicBookingResponse(
        public_id=appointment.public_id,
        service_id=service.public_id,
        service_name=service.name,
        staff_id=staff.public_id,
        staff_name=staff.display_name,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
        client_name=data.client_name,
        client_phone=data.client_phone,
        notes=data.notes,
        custom_fields=appointment.intake_answers or request.custom_fields,
        payment_required=request.payment_required,
        payment_status=payment.status if payment else None,
        payment_link=payment.payment_link if payment else None,
        payment_public_id=payment.id if payment else None,
        # Sin pago online se informa la misma decision que se evaluo arriba
        # (el precio final ya trae la promo cuando la hubo).
        payment_amount=float(payment.amount if payment else request.deposit.amount),
        promotion_code=quote.code if quote else None,
        service_price=float(request.base_price),
        discount_amount=float(quote.discount_amount) if quote else 0.0,
        final_price=float(quote.final_amount) if quote else float(request.base_price),
    )
