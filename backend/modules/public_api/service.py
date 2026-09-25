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

La autogestion del cliente (cancelar y reprogramar, antes 111 y 200 lineas
en el router) vive tambien aca; la fijan los tests de
``tests/integration/test_caracterizacion_autogestion.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog
from fastapi import status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import invalidate_availability
from core.circuit_breaker import CircuitBreakerOpenError
from core.config import settings
from core.database import _apply_tenant_context
from core.exceptions import (
    AppException,
    AppointmentConflictException,
    AppointmentNotFoundException,
    BookingNoticeException,
    OTPException,
    PermissionDeniedException,
    ServiceNotFoundException,
    StaffNotFoundException,
    StoreNotFoundException,
    ValidationException,
)
from core.feature_flags import is_store_feature_enabled
from core.utils import BOOKING_HORIZON_DAYS, today_local
from modules.appointments.guards import (
    awaits_payment,
    is_active,
    reject_already_cancelled,
    reject_inactive,
)
from modules.appointments.model import Appointment, AppointmentStatus
from modules.billing.dependencies import reject_new_public_business_when_suspended
from modules.notifications.model import NotificationType
from modules.notifications.tasks import (
    enqueue_confirmation_email,
    enqueue_registration_email,
    is_deliverable_email,
)
from modules.otp.service import OtpService, mask_phone
from modules.payments.deposit_rules import (
    UNKNOWN_HISTORY,
    ClientHistory,
    DepositDecision,
    DepositRules,
    decide_deposit,
)
from modules.payments.model import JsonValue, OutboxMessage, Payment
from modules.payments.repository import PaymentRepository
from modules.payments.service import (
    MercadoPagoAPIError,
    PaymentGatewayNotConnectedError,
    ProviderPreferenceWithoutLinkError,
    ensure_payment_preference,
    expire_unsealed_preference,
    mercadopago_budget,
)
from modules.promotions.model import PromotionRedemption
from modules.promotions.service import PromotionQuote, quote_promotion, redeem_promotion
from modules.public_api.repository import PublicRepository, RangeRejection
from modules.public_api.schemas import (
    ClientCancelRequest,
    ClientRescheduleRequest,
    PublicBookingCreate,
    PublicBookingResponse,
)
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.users.model import User
from modules.waitlist.events import publish_slot_released
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


# Horizonte de la disponibilidad publica (F1-11, decision 14 del dueno).
PUBLIC_AVAILABILITY_PAST_DAYS = 1
PUBLIC_AVAILABILITY_FUTURE_DAYS = BOOKING_HORIZON_DAYS


def require_public_availability_day(day: date) -> date:
    """El dia de una consulta ANONIMA de disponibilidad, o 422.

    Entre ayer y hoy + 120 dias locales (F1-11): cada fecha es una clave de
    cache y la fecha libre dejaba su cardinalidad sin tope. La aplican
    ``/public/availability`` y la rama sin token de
    ``/appointments/availability`` (revision de perf/f4-back), que comparten
    claves.
    """
    today = today_local()
    earliest = today - timedelta(days=PUBLIC_AVAILABILITY_PAST_DAYS)
    latest = today + timedelta(days=PUBLIC_AVAILABILITY_FUTURE_DAYS)
    if not earliest <= day <= latest:
        raise ValidationException(
            "La fecha esta fuera del rango de reservas: elegi una entre ayer "
            f"y los proximos {PUBLIC_AVAILABILITY_FUTURE_DAYS} dias"
        )
    return day


# ---------------------------------------------------------------------------
# Autogestion: que puede hacer el cliente con SU turno (una sola fuente)
# ---------------------------------------------------------------------------

_CLIENT_PAYMENT_IN_PROGRESS = (
    "Este turno tiene un pago en curso. Para cancelarlo o cambiarlo, "
    "comunicate con la tienda."
)
_CLIENT_PAID_RESCHEDULE = (
    "Este turno ya tiene un pago registrado; contactá a la tienda para reprogramarlo."
)


def client_cancel_denial(
    appointment: Appointment,
    *,
    cancellation_hours: int,
    live_payment: bool,
    now: datetime | None = None,
) -> AppException | None:
    """Por que el cliente NO puede cancelar este turno; ``None`` si puede.

    Unica fuente de la regla: la usan ``cancel_by_client`` (levanta lo que
    devuelve) y el flag ``can_cancel`` del historial, que antes repetia parte
    de las condiciones a mano y mostraba "Cancelar" en turnos que rebotaban.
    El orden es el de la accion: cobro vivo (``awaits_payment``, la condicion
    de la guarda del panel, con un mensaje para el cliente) y despues la
    ventana de la tienda.

    ``live_payment``: el turno tiene un ``Payment`` vivo (un link generado
    desde el panel sobre un turno confirmado, D1 2026-09-25). Lo calcula el
    llamador con ``live_charge_of``: la accion con
    ``PaymentRepository.has_live_charge``, el historial en su mismo SELECT.
    """
    if awaits_payment(appointment, live_payment=live_payment):
        return AppException(
            message=_CLIENT_PAYMENT_IN_PROGRESS,
            http_status=status.HTTP_409_CONFLICT,
            error_code="PAYMENT_APPOINTMENT_REQUIRES_RELEASE",
        )
    ahora = now or now_compatible_with(appointment.starts_at)
    hours_until = (appointment.starts_at - ahora).total_seconds() / 3600
    if hours_until < cancellation_hours:
        return AppException(
            message=f"Solo se puede cancelar con {cancellation_hours}h de anticipación",
            http_status=status.HTTP_409_CONFLICT,
            error_code="CANCELLATION_WINDOW_EXPIRED",
        )
    return None


def client_reschedule_denial(
    appointment: Appointment,
    *,
    cancellation_hours: int,
    paid: bool,
    live_payment: bool,
    now: datetime | None = None,
) -> AppException | None:
    """Por que el cliente NO puede reprogramar este turno; ``None`` si puede.

    Reprogramar cancela el original: primero las reglas de cancelar
    (AUD2-B1-02). Despues, un pago acreditado: el ``Payment`` quedaria
    huerfano apuntando al turno cancelado y el nuevo apareceria impago; eso lo
    maneja la tienda. ``paid`` sale de
    ``PublicRepository.accredited_appointment_ids``.
    """
    denial = client_cancel_denial(
        appointment,
        cancellation_hours=cancellation_hours,
        live_payment=live_payment,
        now=now,
    )
    if denial is not None:
        return denial
    if paid:
        return AppException(
            message=_CLIENT_PAID_RESCHEDULE,
            http_status=status.HTTP_409_CONFLICT,
            error_code="PAID_APPOINTMENT_RESCHEDULE_DENIED",
        )
    return None


def client_may_leave(appointment: Appointment) -> bool:
    """El grafo de estados deja pasar el turno a ``cancelled`` (cancelar y
    reprogramar lo hacen). Es el mismo grafo que aplica
    ``apply_status_transition``: un terminal no se ofrece. Misma regla que
    la guarda de las acciones (``appointments.guards.is_active``)."""
    return is_active(appointment)


async def require_recent_client_otp(
    db: AsyncSession, *, store_id: str, phone: str
) -> None:
    """Autogestion: el email verificado tiene que ser el de ESA ficha.

    Un OTP prueba posesion del EMAIL, no del telefono, y `/public/otp/request`
    es publico: quien pedia el codigo elegia el buzon. Con el predicado viejo
    (`is_recently_verified(store_id, phone)`) saber un telefono ajeno y poner el
    email propio alcanzaba para listar, cancelar y reprogramar los turnos de esa
    persona. 2026-09-20.
    """
    service = OtpService(db)
    if not await service.is_client_contact_verified(store_id=store_id, phone=phone):
        # El motivo se resuelve SOLO en el camino de rechazo y va al log del
        # servidor: es lo unico con lo que se atiende el ticket de un cliente
        # legitimo trabado, y antes los 403 de OTP salian sin ninguna traza
        # (`main.py` no loguea `AppException`).
        logger.warning(
            "otp_self_service_denied",
            store_id=store_id,
            phone=mask_phone(phone),
            reason=await service.client_contact_verification_reason(
                store_id=store_id, phone=phone
            ),
        )
        # Mensaje NEUTRO (regla 20): no dice si el telefono no es cliente, si
        # la ficha no tiene email cargado o si el codigo se verifico contra
        # otro. Cualquiera de las tres seria un oraculo anonimo.
        raise OTPException(
            message="Se requiere validar OTP antes de autogestionar turnos",
            error_code="OTP_VERIFICATION_REQUIRED",
            http_status=status.HTTP_403_FORBIDDEN,
        )


def now_compatible_with(value: datetime) -> datetime:
    now = datetime.now(timezone.utc)
    return now if value.tzinfo else now.replace(tzinfo=None)


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


# Regla 20: la reserva es anonima y el texto de estas excepciones puede traer
# hasta 400 caracteres del cuerpo que devolvio Mercado Pago (o el nombre del
# breaker). Afuera sale un mensaje fijo por caso; al log, solo el tipo y el
# status de MP si lo hay.


def _payment_provider_unavailable(exc: Exception) -> AppException:
    logger.warning(
        "public_booking_payment_provider_unavailable", error_type=type(exc).__name__
    )
    return AppException(
        message="Proveedor de pagos temporalmente no disponible",
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="PAYMENT_PROVIDER_UNAVAILABLE",
    )


def _payment_link_failed(exc: Exception) -> AppException:
    if isinstance(exc, PaymentGatewayNotConnectedError):
        # Precondicion de la tienda, no una falla del proveedor (SEG-04).
        logger.info(
            "public_booking_gateway_not_connected", error_type=type(exc).__name__
        )
        return AppException(
            message="Este negocio no tiene el cobro online disponible en este momento",
            http_status=status.HTTP_409_CONFLICT,
            error_code="PAYMENT_GATEWAY_NOT_CONNECTED",
        )
    logger.warning(
        "public_booking_payment_link_failed",
        error_type=type(exc).__name__,
        provider_status=getattr(exc, "status_code", None),
    )
    return AppException(
        message="No se pudo iniciar el cobro online",
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
    contact_verified: bool
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
        transaccion, con compensacion) -> encolado del mail -> respuesta ->
        cierre de la entrada de lista de espera (best-effort).
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
        # El encolado del mail (F2-01: hasta 2 s de publish en un hilo; el
        # SMTP lo hace el worker) corre sin transaccion: el commit de
        # TenantSession deja otra abierta al reaplicar el contexto (F1-05,
        # R8-05; patron de AUD2-B2-08). No hay nada pendiente: esto solo la
        # cierra, y el contexto vuelve antes de la lista de espera.
        await AsyncSession.commit(self.db)
        try:
            await self._notify_client(request, booking)
        finally:
            await _apply_tenant_context(self.db)
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

        # Un OTP prueba posesion de un EMAIL, no del telefono. El gate de
        # reserva NO recibe ningun email del request: `client_email` es
        # opcional y en el wizard publico es un campo distinto del email del
        # codigo, asi que exigir que coincidan trababa reservas legitimas sin
        # aportar seguridad (quien ataca controla los dos campos). La garantia
        # esta en el despacho: si el telefono tiene ficha con email entregable,
        # el codigo va a ESE buzon. La ramificacion vive en el servicio.
        # 2026-09-20.
        # Una instancia para el request: recuerda la ficha y el veredicto, y
        # el gate y el contacto verificado no vuelven a preguntar (F3-03).
        otp_service = OtpService(self.db)
        if is_store_feature_enabled(store.feature_flags, "otp_booking"):
            await self._require_booking_otp(otp_service, store.id, data.client_phone)
        contact_verified = await otp_service.is_client_contact_verified(
            store_id=store.id,
            phone=data.client_phone,
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
            contact_verified=contact_verified,
            custom_fields=custom_fields,
            base_price=base_price,
            discounted_price=discounted_price,
            history=(
                # Mismo criterio que el preview: un telefono sin CONTACTO
                # verificado no trae el historial de nadie, ni para mostrar ni
                # para cobrar. Si no, quien tipea el telefono de otro hereda
                # (o le carga) sus recargos. Una sola consulta agregada, antes
                # del lock.
                await self.repo.get_client_history(store.id, data.client_phone)
                if contact_verified
                else UNKNOWN_HISTORY
            ),
        )

    @staticmethod
    async def _require_booking_otp(
        otp_service: OtpService, store_id: str, phone: str
    ) -> None:
        if await otp_service.may_book_with_otp(store_id=store_id, phone=phone):
            return
        # El motivo se resuelve SOLO en el camino de rechazo y va al log del
        # servidor: antes los 403 de OTP salian sin ninguna traza (`main.py`
        # no loguea `AppException`), asi que un cliente legitimo trabado era
        # un ticket sin datos.
        logger.warning(
            "otp_booking_denied",
            store_id=store_id,
            phone=mask_phone(phone),
            reason=await otp_service.booking_otp_reason(store_id=store_id, phone=phone),
        )
        raise OTPException(
            message="Se requiere validar OTP antes de reservar",
            error_code="OTP_VERIFICATION_REQUIRED",
            http_status=status.HTTP_403_FORBIDDEN,
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
        contact_verified: bool,
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
            contact_verified=contact_verified,
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
        )
        # Toma el FOR UPDATE del profesional antes de leer disponibilidad
        # (regla 4) y aplica el buffer de la tienda. El servicio ya resuelto
        # viaja (F3-03), y la retencion del slot y el consentimiento van en el
        # INSERT del turno.
        appointment, service, staff = await self.repo.create_appointment(
            store_id=store_id,
            service_public_id=data.service_id,
            service=request.service,
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
            # Un turno esperando la seña retiene el slot solo por una ventana
            # corta: si no se paga, vuelve a estar disponible enseguida en vez
            # de bloquear la agenda hasta la hora del turno. La coordinacion
            # manual si retiene hasta el horario, porque la confirma la tienda.
            expires_at=(
                payment_hold_deadline(request.starts_at_utc)
                if request.payment_required
                else request.starts_at_utc
            ),
            # El schema ya exige accepts_terms (PV-09): todo turno publico nace
            # con el instante del consentimiento. No hay columna de version de
            # terminos; si hace falta, la agrega una migracion.
            terms_accepted_at=datetime.now(timezone.utc),
        )
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
        la disponibilidad (B1-10); el llamador libera la idempotencia. Si MP
        llego a crear la preferencia (respuesta sin link de checkout), se
        manda a vencer despues de la compensacion, como en el panel.
        """
        payment = booking.payment
        if not request.payment_required or payment is None:
            return
        # Leidos antes: la compensacion borra el turno y el cobro.
        payment_id, appointment_id = payment.id, booking.appointment.id
        try:
            # Presupuesto total de la cadena de MP (F1-04): agotarlo es
            # MercadoPagoAPIError(transient=True) y se compensa como cualquier
            # fallo del proveedor, antes de que nginx corte con un 504 y el
            # cliente reintente contra una reserva ya commiteada.
            with mercadopago_budget(settings.MERCADOPAGO_REQUEST_BUDGET_SECONDS):
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
        except (MercadoPagoAPIError, RuntimeError, TimeoutError) as exc:
            # MercadoPagoAPIError es RuntimeError; se nombra porque es EL caso.
            # TimeoutError por si un tope ajeno al presupuesto corta la red:
            # antes no era RuntimeError y el turno quedaba retenido sin link.
            await revert_failed_booking(self.db, self.cache, booking.appointment)
            if isinstance(exc, ProviderPreferenceWithoutLinkError):
                await expire_unsealed_preference(
                    self.db,
                    store_id=request.store_id,
                    appointment_id=appointment_id,
                    payment_id=payment_id,
                    preference_id=exc.preference_id,
                )
            raise _payment_link_failed(exc)

    async def _notify_client(self, request: _BookingRequest, booking: _Booking) -> None:
        # Aviso al cliente por mail (best-effort, fuera de la transaccion).
        # Antes la condicion exigia CONFIRMED y el turno nace PENDING o
        # PENDING_PAYMENT: nunca salia nada. Ahora "reserva registrada" al
        # crear, y "turno confirmado" solo si ya nacio confirmado.
        # F2-01 (R1-04, 2026-09-24): se ENCOLA y lo manda el worker; el 201
        # esperaba al SMTP. Un email tecnico no se encola.
        appointment = booking.appointment
        if not is_deliverable_email(appointment.client_email):
            return
        if appointment.status == AppointmentStatus.CONFIRMED.value:
            await enqueue_confirmation_email(
                store_id=request.store_id, appointment_id=appointment.id
            )
        else:
            await enqueue_registration_email(
                store_id=request.store_id, appointment_id=appointment.id
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

    # ------------------------------------------------------------------
    # Autogestion del cliente
    # ------------------------------------------------------------------

    async def cancel_by_client(
        self, public_id: str, data: ClientCancelRequest
    ) -> PublicBookingResponse:
        """El cliente cancela su turno: commit -> invalidacion -> respuesta."""
        appointment, client = await self._lock_client_appointment(public_id, data.phone)
        # Ya cancelado: 409 como el panel, sin republicar el cupo ni avisar
        # otra vez al dueno (revision de perf/f4-pay, 2026-09-25).
        reject_already_cancelled(appointment)
        # Cobro vivo (solo lo suelta release(), que vence antes la preferencia
        # en MP) y ventana de la tienda: las mismas reglas que el flag
        # ``can_cancel`` del historial.
        denial = client_cancel_denial(
            appointment,
            cancellation_hours=await self._cancellation_hours(appointment.store_id),
            live_payment=await self._has_live_charge(appointment),
        )
        if denial is not None:
            raise denial

        appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        publish_slot_released(
            self.db,
            store_id=appointment.store_id,
            staff_id=appointment.staff_id,
            service_id=appointment.service_id,
            appointment_id=appointment.id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            reason="client_cancelled",
        )
        service = await self._notify_owner_of_cancellation(
            appointment, client, data.reason
        )
        await self.db.commit()
        await self.db.refresh(appointment)

        await invalidate_availability(
            self.cache, appointment.store_id, appointment.starts_at
        )
        stf_res = await self.db.execute(
            select(Staff).where(Staff.id == appointment.staff_id)
        )
        return _self_service_response(
            appointment, service, stf_res.scalar_one_or_none(), client, data.phone
        )

    async def reschedule_by_client(
        self, public_id: str, data: ClientRescheduleRequest
    ) -> PublicBookingResponse:
        """Reprograma: cancela el original y crea el nuevo en un savepoint.

        El llamador maneja la idempotencia (reserva, liberacion y replay).
        """
        original, client = await self._lock_client_appointment(public_id, data.phone)
        # Un turno terminal no se reprograma (ni vuelve a la vida).
        reject_inactive(original)
        # Reprogramar cancela el turno original: le corresponden los mismos
        # guards que a cancelar, incluida la ventana de la tienda (AUD2-B1-02).
        # Sin ella, a quien se le paso la hora de cancelar le alcanzaba con
        # mover el turno a una fecha lejana para liberar el horario igual.
        # Y un turno con pago acreditado no se mueve desde el cliente. Las
        # mismas reglas que el flag ``can_reschedule`` del historial.
        denial = client_reschedule_denial(
            original,
            cancellation_hours=await self._cancellation_hours(original.store_id),
            paid=bool(await self.repo.accredited_appointment_ids([original.id])),
            live_payment=await self._has_live_charge(original),
        )
        if denial is not None:
            raise denial
        service, staff = await self._service_and_staff(original)
        new_ends_at = data.new_starts_at + timedelta(minutes=service.duration_minutes)
        await self._check_new_slot(original, staff, data.new_starts_at, new_ends_at)

        # El estado se lee ANTES de cancelar el original: la copia lo conserva
        # (AUD2-B1-14) y ``apply_status_transition`` ya lo habria pisado.
        estado_previo = original.status
        async with self.db.begin_nested():
            original.apply_status_transition(AppointmentStatus.CANCELLED)
            publish_slot_released(
                self.db,
                store_id=original.store_id,
                staff_id=original.staff_id,
                service_id=original.service_id,
                appointment_id=original.id,
                starts_at=original.starts_at,
                ends_at=original.ends_at,
                reason="client_rescheduled",
            )
            new_appointment = _rescheduled_copy(
                original, client, service, data, new_ends_at, estado_previo
            )
            self.db.add(new_appointment)
            await self.db.flush()

        await self.db.commit()
        await self.db.refresh(new_appointment)

        await invalidate_availability(
            self.cache, original.store_id, original.starts_at, data.new_starts_at
        )
        return _self_service_response(
            new_appointment, service, staff, client, data.phone
        )

    async def _lock_client_appointment(
        self, public_id: str, phone: str
    ) -> tuple[Appointment, User]:
        """Lock del turno (TOCTOU), titularidad y OTP, en ese orden.

        Titularidad + OTP ANTES de cualquier chequeo que revele estado del
        turno: sin esto, quien solo conozca el public_id sabria si esta
        esperando pago (fuga menor de estado).
        """
        appt_res = await self.db.execute(
            select(Appointment).where(Appointment.id == public_id).with_for_update()
        )
        appointment = appt_res.scalar_one_or_none()
        if not appointment:
            raise AppointmentNotFoundException(public_id=public_id)

        client = await self.repo.get_client_by_phone(appointment.store_id, phone)
        if not client or client.id != appointment.client_id:
            raise PermissionDeniedException(
                action="El teléfono no coincide con el titular del turno"
            )

        await require_recent_client_otp(
            self.db, store_id=appointment.store_id, phone=phone
        )
        return appointment, client

    async def _cancellation_hours(self, store_id: str) -> int:
        """Ventana de cancelacion de la tienda (2 h si no se encuentra)."""
        store = await self.repo.get_store_by_id(store_id)
        return getattr(store, "cancellation_hours", 2) if store else 2

    async def _has_live_charge(self, appointment: Appointment) -> bool:
        """El turno (ya lockeado) tiene un cobro vivo: un link del panel (D1)."""
        return await PaymentRepository(self.db).has_live_charge(
            appointment.id, appointment.store_id
        )

    async def _notify_owner_of_cancellation(
        self, appointment: Appointment, client: User, reason: str | None
    ) -> Service | None:
        """Aviso al duenio por outbox; devuelve el servicio (se lee una vez).

        La tienda se entera de que le cancelaron: antes el cliente cancelaba y
        el dueno solo lo notaba mirando la agenda. Una sola lectura del
        servicio: la usan el aviso y la respuesta (B1-21).
        """
        svc_res = await self.db.execute(
            select(Service).where(Service.id == appointment.service_id)
        )
        service = svc_res.scalar_one_or_none()
        aviso: dict[str, JsonValue] = {
            "appointment_id": appointment.id,
            "client_name": client.full_name or "Un cliente",
            "service_name": getattr(service, "name", ""),
            "starts_at": appointment.starts_at.isoformat(),
        }
        # El motivo que dejo el cliente viaja al aviso del duenio en una sola
        # linea: sin CR/LF no puede partir la notificacion ni el mail (B1-23).
        motivo = " ".join((reason or "").split())
        if motivo:
            aviso["reason"] = motivo
        self.db.add(
            OutboxMessage(
                store_id=appointment.store_id,
                event_type=NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value,
                payload=aviso,
            )
        )
        return service

    async def _service_and_staff(self, original: Appointment) -> tuple[Service, Staff]:
        svc_res = await self.db.execute(
            select(Service).where(Service.id == original.service_id)
        )
        service = svc_res.scalar_one_or_none()
        if not service:
            raise ServiceNotFoundException(identifier=str(original.service_id))

        stf_res = await self.db.execute(
            select(Staff).where(Staff.id == original.staff_id)
        )
        staff = stf_res.scalar_one_or_none()
        if not staff:
            raise StaffNotFoundException(identifier=str(original.staff_id))
        return service, staff

    async def _check_new_slot(
        self,
        original: Appointment,
        staff: Staff,
        new_starts_at: datetime,
        new_ends_at: datetime,
    ) -> None:
        """El nuevo horario respeta las MISMAS reglas que una reserva nueva.

        Antelacion minima, agenda del profesional, bloqueos y choques. Horario,
        bloqueo y choque salen de la MISMA funcion que el alta publica (B1-19);
        el lock del profesional y la relectura bajo lock quedan en el
        repositorio (regla 4); el turno que se mueve no choca consigo mismo.
        """
        new_starts_utc = (
            new_starts_at
            if new_starts_at.tzinfo
            else new_starts_at.replace(tzinfo=timezone.utc)
        )
        store = await self.repo.get_store_by_id(original.store_id)
        notice_hours = getattr(store, "min_booking_notice_hours", 2) or 0
        if new_starts_utc < datetime.now(timezone.utc) + timedelta(hours=notice_hours):
            raise BookingNoticeException(notice_hours)
        rechazo = await self.repo.staff_can_take_range(
            staff.id,
            new_starts_at,
            new_ends_at,
            buffer_minutes=getattr(store, "buffer_minutes", 0) or 0,
            exclude_appointment_id=original.id,
        )
        if rechazo is RangeRejection.OUT_OF_SCHEDULE:
            raise AppException(
                message="El profesional no atiende en ese horario",
                http_status=status.HTTP_409_CONFLICT,
                error_code="OUT_OF_SCHEDULE",
            )
        if rechazo is RangeRejection.BLOCKED:
            raise AppException(
                message="Ese horario esta bloqueado en la agenda",
                http_status=status.HTTP_409_CONFLICT,
                error_code="SCHEDULE_BLOCKED",
            )
        if rechazo is RangeRejection.TAKEN:
            raise AppointmentConflictException()


def _rescheduled_copy(
    original: Appointment,
    client: User,
    service: Service,
    data: ClientRescheduleRequest,
    new_ends_at: datetime,
    estado_previo: str,
) -> Appointment:
    # El turno movido conserva el estado del original (AUD2-B1-14): antes
    # nacia siempre con el default de la columna, asi que un turno confirmado
    # volvia a "pendiente de confirmar" sin que nadie se enterara y el job de
    # expiracion lo levantaba a la hora de inicio. A esta altura no hay sena
    # de por medio -``client_reschedule_denial`` frena el ``pending_payment``,
    # el cobro vivo (link del panel, D1) y el pago acreditado-,
    # asi que lo unico que se conserva es un ``confirmed`` sin cobro, y con el
    # se va el ``expires_at``: no hay retencion que vencer.
    confirmado = estado_previo == AppointmentStatus.CONFIRMED.value
    return Appointment(
        store_id=original.store_id,
        staff_id=original.staff_id,
        service_id=original.service_id,
        client_id=original.client_id,
        starts_at=data.new_starts_at,
        ends_at=new_ends_at,
        duration_minutes=service.duration_minutes,
        # Preservar el precio congelado del turno original.
        price_amount=original.price_amount,
        client_name=client.full_name or client.email,
        client_email=client.email,
        client_phone=client.phone,
        notes=original.notes,
        intake_answers=original.intake_answers or {},
        idempotency_key=data.idempotency_key,
        status=(
            AppointmentStatus.CONFIRMED.value
            if confirmado
            else AppointmentStatus.PENDING.value
        ),
        # Mismo criterio que el alta publica para un turno sin cobro online:
        # retiene el horario hasta que empieza y despues lo levanta el job de
        # expiracion si nadie lo confirmo (B1-22).
        expires_at=None if confirmado else data.new_starts_at,
    )


def _self_service_response(
    appointment: Appointment,
    service: Service | None,
    staff: Staff | None,
    client: User,
    phone: str,
) -> PublicBookingResponse:
    return PublicBookingResponse(
        public_id=appointment.public_id,
        service_id=service.public_id if service else str(appointment.service_id),
        service_name=service.name if service else "",
        staff_id=staff.public_id if staff else str(appointment.staff_id),
        staff_name=staff.display_name if staff else "",
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
        client_name=client.full_name or "Cliente",
        client_phone=phone,
        notes=appointment.notes,
        custom_fields=appointment.intake_answers or {},
    )


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
