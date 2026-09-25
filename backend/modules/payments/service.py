from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from decimal import Decimal, ROUND_HALF_UP
from json import JSONDecodeError
from urllib.parse import urlencode, urlparse
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import cast

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError
from core.config import settings
from core.crypto import decrypt_secret, encrypt_secret
from core.database import _apply_tenant_context
from core.exceptions import AppException
from core.observability import report_exception
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import (
    JsonValue,
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
    is_placeholder_preference_id,
    external_reference_for,
)
from modules.services.model import Service
from modules.payments.links import ImportesDelLink, record_retired_link
from modules.payments.model import (  # reexportado: lo importan jobs y tests
    EVENT_PREFERENCE_EXPIRE as EVENT_PREFERENCE_EXPIRE,
)
from modules.stores.media import absolute_media_url
from modules.stores.model import Store
from modules.users.model import User

logger = structlog.get_logger()


ACTIVE_APPOINTMENT_STATUSES = {
    AppointmentStatus.PENDING.value,
    AppointmentStatus.PENDING_PAYMENT.value,
    AppointmentStatus.CONFIRMED.value,
}
# Timeouts por fase de httpx (F1-04, R8-01). Antes era un 20 s plano por
# fase: una request lenta podia sumar mucho mas que eso.
MERCADOPAGO_HTTP_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0)
# Tope duro de UNA request a MP, fases sumadas. Lo asume la cuenta del lease
# de vencimientos (``jobs.MP_REQUEST_TIMEOUT``): no puede ser mayor.
MERCADOPAGO_REQUEST_DEADLINE_SECONDS = 20.0
_mercadopago_breaker = AsyncCircuitBreaker(
    name="mercadopago",
    failure_threshold=settings.PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout_seconds=settings.PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS,
)


# Cliente httpx compartido (F1-04, R8-08, R11-20). Antes cada llamada abria
# uno nuevo: SSLContext + certifi sincronos (5-20 ms de loop) y DNS + TCP + TLS
# cada vez. Sus conexiones quedan atadas al event loop que las abrio, asi que
# se cachea POR LOOP: la API tiene uno por proceso y Celery otro por proceso
# hijo (``core.worker_loop``, regla 8). Un cliente de otro loop no se reusa.
# La API lo cierra en el lifespan (``close_mercadopago_client``).
_http_client: httpx.AsyncClient | None = None
_http_client_loop: asyncio.AbstractEventLoop | None = None


def _mercadopago_http_client() -> httpx.AsyncClient:
    global _http_client, _http_client_loop
    loop = asyncio.get_running_loop()
    if _http_client is None or _http_client_loop is not loop or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=MERCADOPAGO_HTTP_TIMEOUT)
        _http_client_loop = loop
    return _http_client


async def close_mercadopago_client() -> None:
    """Cierra el cliente compartido si es de este loop (apagado de la API)."""
    global _http_client, _http_client_loop
    client, loop = _http_client, _http_client_loop
    _http_client, _http_client_loop = None, None
    if client is None or client.is_closed:
        return
    if loop is asyncio.get_running_loop():
        await client.aclose()


# Vencimiento del presupuesto total del request en curso (reloj del loop).
# Lo fija ``mercadopago_budget`` y lo respeta cada request a MP POR DEBAJO del
# circuit breaker: un ``asyncio.timeout`` por fuera cancelaria la llamada en
# medio del breaker y dejaria su sonda de half-open tomada para siempre.
_budget_deadline: ContextVar[float | None] = ContextVar(
    "mercadopago_budget_deadline", default=None
)


@contextmanager
def mercadopago_budget(seconds: float) -> Iterator[None]:
    """Presupuesto total para toda la cadena de llamadas a MP de un request.

    Preferencia + refresh OAuth + reintento no pueden pasar de ``seconds``
    sumados; agotarlo es ``MercadoPagoAPIError(transient=True)`` y el
    llamador compensa. Anidado, gana el vencimiento mas cercano.
    """
    deadline = asyncio.get_running_loop().time() + seconds
    current = _budget_deadline.get()
    if current is not None:
        deadline = min(deadline, current)
    token = _budget_deadline.set(deadline)
    try:
        yield
    finally:
        _budget_deadline.reset(token)


def _request_deadline_seconds() -> float:
    """Lo que le queda a esta request: su tope o el resto del presupuesto."""
    deadline = _budget_deadline.get()
    if deadline is None:
        return MERCADOPAGO_REQUEST_DEADLINE_SECONDS
    remaining = deadline - asyncio.get_running_loop().time()
    return min(MERCADOPAGO_REQUEST_DEADLINE_SECONDS, remaining)


async def _send_to_mercadopago(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, JsonValue] | None = None,
    form_data: dict[str, str] | None = None,
) -> httpx.Response:
    """Una request al cliente compartido, acotada por su tope y el presupuesto.

    Levanta ``TimeoutError`` si se agoto el tiempo (sea de httpx o propio) y
    ``httpx.RequestError`` si la red fallo; cada llamador lo traduce.
    """
    remaining = _request_deadline_seconds()
    if remaining <= 0:
        raise TimeoutError("presupuesto de Mercado Pago agotado")
    try:
        async with asyncio.timeout(remaining):
            return await _mercadopago_http_client().request(
                method, url, headers=headers, json=json_body, data=form_data
            )
    except httpx.TimeoutException as exc:
        raise TimeoutError(str(exc)) from exc


class MercadoPagoAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        transient: bool = False,
    ) -> None:
        self.status_code = status_code
        self.transient = transient
        super().__init__(message)


class PaymentGatewayNotConnectedError(RuntimeError):
    """La tienda no tiene una cuenta de Mercado Pago activa para cobrar.

    Es una precondicion de la tienda, no una falla del proveedor (SEG-04).
    Hereda de RuntimeError para que la compensacion existente la siga viendo.
    """


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean_payload(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _clean_payload(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_clean_payload(item) for item in value if item is not None]
    return value


def _placeholder_link(appointment_id: str) -> tuple[str, str]:
    """(preference_id, payment_link) falsos: marcan que falta pedirle el link a MP."""
    return (
        f"pref_{appointment_id}",
        f"https://payments.shifty.local/pay/{appointment_id}",
    )


def new_link_ref() -> str:
    """Nonce de un link de pago: corto, unico y sin ``:``."""
    return secrets.token_hex(8)


def _is_placeholder_preference(preference_id: str | None) -> bool:
    return is_placeholder_preference_id(preference_id)


def _is_placeholder_payment_link(payment_link: str | None) -> bool:
    return not payment_link or payment_link.startswith("https://payments.shifty.local/")


def _normalize_payer_email(email: str | None) -> str | None:
    if not email:
        return None
    if email.endswith(".noreply"):
        return None
    return email


async def _resolve_appointment_payer(
    db: AsyncSession, appointment: Appointment
) -> tuple[str | None, str | None]:
    client = appointment.__dict__.get("client")
    if client is None and appointment.client_id:
        result = await db.execute(select(User).where(User.id == appointment.client_id))
        client = result.scalar_one_or_none()

    if client is None:
        return appointment.client_name or None, appointment.client_email

    resolved_name = client.full_name or client.email
    return resolved_name or None, client.email


def _booking_return_url(store: Store, payment: Payment) -> str:
    base_url = settings.FRONTEND_URL.rstrip("/")
    query = urlencode(
        {
            "payment_id": payment.id,
            "store_id": store.public_id,
        }
    )
    return f"{base_url}/booking/{store.slug}?{query}"


def _notification_url(store: Store) -> str:
    base_url = settings.PUBLIC_API_URL.rstrip("/")
    return f"{base_url}/payments/webhooks/mercadopago?store_id={store.public_id}"


def _resolve_checkout_link(payload: dict[str, JsonValue]) -> str | None:
    # Checkout Pro test purchases use test seller/buyer accounts with the
    # regular init_point. Forcing sandbox_init_point in non-production mixes
    # environments and Mercado Pago rejects otherwise valid test payments.
    value = payload.get("init_point") or payload.get("sandbox_init_point")
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "mercadopago.com"
        or hostname.endswith(".mercadopago.com")
        or hostname == "mercadopago.com.ar"
        or hostname.endswith(".mercadopago.com.ar")
    ):
        return None
    return value


def calculate_service_payment_amount(
    service: Service, *, base_price: Decimal | None = None
) -> Decimal:
    mode = getattr(service, "deposit_mode", "none") or "none"
    payment_type = getattr(service, "deposit_type", "percent") or "percent"
    raw_amount = getattr(service, "deposit_amount", None)
    service_price = _money(
        base_price if base_price is not None else Decimal(str(service.price or 0))
    )

    if mode == "none":
        return Decimal("0.00")

    if payment_type == "full":
        return service_price

    if raw_amount is None:
        return Decimal("0.00")

    configured_amount = _money(Decimal(str(raw_amount)))
    if payment_type == "fixed":
        return min(configured_amount, service_price)
    if payment_type == "percent":
        return _money(service_price * configured_amount / Decimal("100"))
    return Decimal("0.00")


async def _mercadopago_api_request(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    # Presupuesto ya agotado: no sale ninguna request, asi que no es una falla
    # de MP y no pasa por el breaker (no suma ni ocupa la sonda half-open).
    if _request_deadline_seconds() <= 0:
        raise MercadoPagoAPIError(
            "Se agoto el tiempo para hablar con Mercado Pago", transient=True
        )
    result = await _mercadopago_breaker.call(
        lambda: _perform_mercadopago_request(
            access_token,
            method=method,
            path=path,
            json_body=json_body,
        ),
        should_record_failure=_should_trip_mercadopago_breaker,
    )
    return cast(dict[str, JsonValue], result)


def _should_trip_mercadopago_breaker(exc: Exception) -> bool:
    return isinstance(exc, MercadoPagoAPIError) and exc.transient


async def _perform_mercadopago_request(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = await _send_to_mercadopago(
            method,
            f"{settings.MERCADOPAGO_API_BASE_URL}{path}",
            headers=headers,
            json_body=json_body,
        )
    except TimeoutError as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago no respondio a tiempo", transient=True
        ) from exc
    except httpx.RequestError as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago no esta disponible", transient=True
        ) from exc

    if response.status_code >= 500:
        detail = response.text[:400]
        raise MercadoPagoAPIError(
            detail or f"Mercado Pago devolvio HTTP {response.status_code}",
            status_code=response.status_code,
            transient=True,
        )
    if response.status_code >= 400:
        detail = response.text[:400]
        raise MercadoPagoAPIError(
            detail or f"Mercado Pago devolvio HTTP {response.status_code}",
            status_code=response.status_code,
            transient=False,
        )
    if not response.content:
        return {}
    try:
        return cast(dict[str, JsonValue], response.json())
    except (ValueError, JSONDecodeError) as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago devolvio una respuesta invalida", transient=True
        ) from exc


async def _get_gateway_config(
    db: AsyncSession, store_id: str
) -> PaymentGatewayConfig | None:
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store_id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    return result.scalar_one_or_none()


# Configuracion del gateway ya resuelta por tienda. La arma un lote una sola
# vez (load_gateway_configs) y la pasa hacia abajo: cada request HTTP a MP
# arrastraba su propia consulta a payment_gateway_configs, y el inbox la
# repetia por cada webhook (regla 12; 2026-09-17, B2-13).
GatewayConfigs = Mapping[str, PaymentGatewayConfig]

# Como se persiste una config refrescada por OAuth. None (el default) es el
# camino de siempre: flush dentro de la transaccion del llamador (requests).
# Un job que habla con MP sin transaccion abierta pasa el suyo (S-02).
PersistRefresh = Callable[[PaymentGatewayConfig], Awaitable[None]]


async def load_gateway_configs(
    db: AsyncSession, store_ids: Iterable[str | None]
) -> dict[str, PaymentGatewayConfig]:
    """Una lectura con ``in_()`` para todas las tiendas del lote.

    Una tienda sin fila queda fuera del dict: ``configs.get(store_id)`` es
    None, igual que lo que devolvia ``_get_gateway_config``.
    """
    ids = {store_id for store_id in store_ids if store_id}
    if not ids:
        return {}
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id.in_(ids),
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    return {config.store_id: config for config in result.scalars().all()}


async def resolve_gateway_config(
    db: AsyncSession, store_id: str, configs: GatewayConfigs | None = None
) -> PaymentGatewayConfig | None:
    """La config del lote si vino; si no, la consulta de siempre."""
    if configs is not None:
        return configs.get(store_id)
    return await _get_gateway_config(db, store_id)


async def _get_store(db: AsyncSession, store_id: str) -> Store | None:
    result = await db.execute(select(Store).where(Store.id == store_id))
    return result.scalar_one_or_none()


def _resolve_access_token(config: PaymentGatewayConfig | None) -> str | None:
    if not config or not config.encrypted_access_token:
        return None
    try:
        return decrypt_secret(config.encrypted_access_token)
    except Exception:
        return None


def _resolve_refresh_token(config: PaymentGatewayConfig | None) -> str | None:
    if not config or not config.encrypted_refresh_token:
        return None
    try:
        return decrypt_secret(config.encrypted_refresh_token)
    except Exception:
        return None


def mercadopago_oauth_is_configured() -> bool:
    return bool(
        settings.MERCADOPAGO_OAUTH_CLIENT_ID
        and settings.MERCADOPAGO_OAUTH_CLIENT_SECRET
        and settings.MERCADOPAGO_OAUTH_REDIRECT_URI
    )


def build_mercadopago_oauth_authorization_url(
    *, state: str, code_challenge: str
) -> str:
    if not mercadopago_oauth_is_configured():
        raise RuntimeError("Mercado Pago OAuth no esta configurado")
    query = urlencode(
        {
            "client_id": settings.MERCADOPAGO_OAUTH_CLIENT_ID,
            "response_type": "code",
            "platform_id": "mp",
            "state": state,
            "redirect_uri": settings.MERCADOPAGO_OAUTH_REDIRECT_URI,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": "read write offline_access",
        }
    )
    return f"{settings.MERCADOPAGO_OAUTH_AUTH_URL}?{query}"


async def _mercadopago_oauth_token_request(
    form_data: dict[str, str],
) -> dict[str, JsonValue]:
    if not mercadopago_oauth_is_configured():
        raise RuntimeError("Mercado Pago OAuth no esta configurado")

    try:
        response = await _send_to_mercadopago(
            "POST",
            f"{settings.MERCADOPAGO_API_BASE_URL}/oauth/token",
            form_data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
    except TimeoutError as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago no respondio a tiempo durante OAuth", transient=True
        ) from exc
    except httpx.RequestError as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago no esta disponible para completar OAuth", transient=True
        ) from exc

    if response.status_code >= 400:
        detail = response.text[:400] or f"HTTP {response.status_code}"
        raise RuntimeError(f"Mercado Pago rechazo OAuth: {detail}")

    try:
        return cast(dict[str, JsonValue], response.json())
    except ValueError as exc:
        raise RuntimeError(
            "Mercado Pago devolvio una respuesta OAuth invalida"
        ) from exc


async def exchange_mercadopago_oauth_code(
    *, code: str, code_verifier: str
) -> dict[str, JsonValue]:
    return await _mercadopago_oauth_token_request(
        {
            "client_id": settings.MERCADOPAGO_OAUTH_CLIENT_ID or "",
            "client_secret": settings.MERCADOPAGO_OAUTH_CLIENT_SECRET or "",
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.MERCADOPAGO_OAUTH_REDIRECT_URI or "",
            "code_verifier": code_verifier,
        }
    )


async def refresh_mercadopago_oauth_connection(
    db: AsyncSession,
    *,
    config: PaymentGatewayConfig,
    persist: PersistRefresh | None = None,
) -> PaymentGatewayConfig:
    refresh_token = _resolve_refresh_token(config)
    if not refresh_token:
        raise RuntimeError("La conexion OAuth de Mercado Pago no tiene refresh token")

    token_payload = await _mercadopago_oauth_token_request(
        {
            "client_id": settings.MERCADOPAGO_OAUTH_CLIENT_ID or "",
            "client_secret": settings.MERCADOPAGO_OAUTH_CLIENT_SECRET or "",
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
    apply_mercadopago_oauth_payload(config, token_payload)
    if persist is None:
        await db.flush()
    else:
        await persist(config)
    return config


async def exchange_mercadopago_oauth_code_without_transaction(
    db: AsyncSession, *, code: str, code_verifier: str
) -> dict[str, JsonValue]:
    """Canje del codigo OAuth sin transaccion abierta (F1-05, R8-05).

    Patron de AUD2-B2-08: lo que el callback leyo antes (el actor) dejaba la
    transaccion abierta y la conexion "idle in transaction" durante el POST a
    MP. Commit PLANO de ``AsyncSession`` (el de ``TenantSession`` reaplica el
    contexto y la reabre en el acto), red con el presupuesto del request, y
    el contexto (el bypass del callback) se reaplica antes de volver a la
    base.
    """
    await AsyncSession.commit(db)
    try:
        with mercadopago_budget(settings.MERCADOPAGO_REQUEST_BUDGET_SECONDS):
            return await exchange_mercadopago_oauth_code(
                code=code, code_verifier=code_verifier
            )
    finally:
        await _apply_tenant_context(db)


async def refresh_mercadopago_oauth_without_transaction(
    db: AsyncSession, *, config: PaymentGatewayConfig
) -> PaymentGatewayConfig:
    """Refresh OAuth pedido desde el panel, sin transaccion abierta (F1-05).

    Mismo patron que el canje; la config refrescada se persiste en su propia
    transaccion corta con el contexto reaplicado (``persist_gateway_refresh``),
    igual que el webhook y los jobs.
    """
    # Import diferido: jobs importa este modulo.
    from modules.payments.jobs import persist_gateway_refresh

    await AsyncSession.commit(db)
    try:
        with mercadopago_budget(settings.MERCADOPAGO_REQUEST_BUDGET_SECONDS):
            return await refresh_mercadopago_oauth_connection(
                db, config=config, persist=partial(persist_gateway_refresh, db)
            )
    finally:
        await _apply_tenant_context(db)


def apply_mercadopago_oauth_payload(
    config: PaymentGatewayConfig, token_payload: dict[str, JsonValue]
) -> None:
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Mercado Pago no devolvio access_token")

    config.encrypted_access_token = encrypt_secret(access_token) or ""

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if refresh_token:
        config.encrypted_refresh_token = encrypt_secret(refresh_token)

    public_key = str(token_payload.get("public_key") or "").strip()
    if public_key:
        config.public_key = public_key

    oauth_user_id = str(token_payload.get("user_id") or "").strip()
    if oauth_user_id:
        config.oauth_user_id = oauth_user_id

    oauth_scope = str(token_payload.get("scope") or "").strip()
    if oauth_scope:
        config.oauth_scope = oauth_scope

    config.connection_mode = "oauth"
    config.oauth_connected_at = datetime.now(timezone.utc)


async def _mercadopago_api_request_for_store(
    db: AsyncSession,
    *,
    store_id: str,
    method: str,
    path: str,
    json_body: dict[str, JsonValue] | None = None,
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> dict[str, JsonValue] | None:
    config = await resolve_gateway_config(db, store_id, configs)
    access_token = _resolve_access_token(config)
    if not access_token:
        return None

    try:
        return await _mercadopago_api_request(
            access_token,
            method=method,
            path=path,
            json_body=json_body,
        )
    except MercadoPagoAPIError as exc:
        if (
            exc.status_code == 401
            and config is not None
            and config.connection_mode == "oauth"
            and _resolve_refresh_token(config)
            and mercadopago_oauth_is_configured()
        ):
            refreshed_config = await refresh_mercadopago_oauth_connection(
                db, config=config, persist=persist_refresh
            )
            refreshed_access_token = _resolve_access_token(refreshed_config)
            if not refreshed_access_token:
                raise RuntimeError(
                    "No se pudo renovar la conexion OAuth de Mercado Pago"
                )
            return await _mercadopago_api_request(
                refreshed_access_token,
                method=method,
                path=path,
                json_body=json_body,
            )
        raise


@dataclass(frozen=True)
class PreparedPreference:
    """Todo lo que la preferencia necesita de la base, leido ANTES de la red.

    Con esto la llamada a MP no vuelve a consultar nada: quien la hace puede
    cerrar la transaccion antes de salir (F1-05, regla 5).
    """

    store_id: str
    payload: dict[str, JsonValue]
    configs: dict[str, PaymentGatewayConfig]


async def request_mercadopago_preference(
    db: AsyncSession,
    prepared: PreparedPreference,
    *,
    persist_refresh: PersistRefresh | None = None,
) -> dict[str, JsonValue] | None:
    """El POST a MP con la config ya leida: no consulta la base."""
    return await _mercadopago_api_request_for_store(
        db,
        store_id=prepared.store_id,
        method="POST",
        path="/checkout/preferences",
        json_body=prepared.payload,
        configs=prepared.configs,
        persist_refresh=persist_refresh,
    )


async def prepare_mercadopago_preference(
    db: AsyncSession,
    *,
    payment: Payment,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount: Decimal,
    link_ref: str | None,
) -> PreparedPreference | None:
    """Lecturas de la preferencia (gateway, tienda, pagador). None: sin token.

    ``link_ref``: nonce del link que se pide; va en la ``external_reference``
    (``external_reference_for``) para que el webhook sepa de que link es cada
    pago sin depender de ``preference_id``, que el pago de MP no trae.
    """
    config = await _get_gateway_config(db, store_id)
    if config is None or not _resolve_access_token(config):
        return None

    store = await _get_store(db, store_id)
    if not store:
        raise RuntimeError("No encontramos la tienda del pago")

    payer_name, payer_email = await _resolve_appointment_payer(db, appointment)

    payload = cast(
        dict[str, JsonValue],
        _clean_payload(
            {
                "items": [
                    {
                        "id": service.public_id,
                        "title": service.name,
                        "description": service.description,
                        # Una imagen subida es una ruta relativa (F1-28): el
                        # checkout de MP la muestra fuera del sitio.
                        "picture_url": absolute_media_url(
                            service.image_url, settings.PUBLIC_API_URL
                        ),
                        "quantity": 1,
                        "currency_id": payment.currency or "ARS",
                        "unit_price": float(amount),
                    }
                ],
                "payer": {
                    "name": payer_name,
                    "email": _normalize_payer_email(payer_email),
                },
                "external_reference": external_reference_for(appointment.id, link_ref),
                "notification_url": _notification_url(store),
                "back_urls": {
                    "success": _booking_return_url(store, payment),
                    "failure": _booking_return_url(store, payment),
                    "pending": _booking_return_url(store, payment),
                },
                "auto_return": "approved",
                "binary_mode": True,
                "expires": True,
                # El checkout vence junto con la retencion del slot, para que
                # nadie pague una seña de un turno que ya se libero.
                "expiration_date_to": (
                    appointment.expires_at or appointment.starts_at
                ).isoformat(),
                "metadata": {
                    "appointment_id": appointment.id,
                    "store_id": store.id,
                    "store_public_id": store.public_id,
                    "payment_id": payment.id,
                },
            },
        ),
    )
    return PreparedPreference(
        store_id=store_id, payload=payload, configs={store_id: config}
    )


# ``EVENT_PREFERENCE_EXPIRE`` ("vencer este link en MP", B1-04) vive en
# ``payments.model`` y se reexporta desde aca.


async def expire_mercadopago_preference(
    db: AsyncSession,
    *,
    store_id: str,
    preference_id: str,
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> None:
    if _is_placeholder_preference(preference_id):
        return
    expiration = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    response = await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="PUT",
        path=f"/checkout/preferences/{preference_id}",
        json_body={
            "expires": True,
            "expiration_date_to": expiration,
        },
        configs=configs,
        persist_refresh=persist_refresh,
    )
    if response is None:
        raise RuntimeError(
            "No se pudo vencer la preferencia porque la tienda no tiene una conexion activa"
        )


async def fetch_mercadopago_payment(
    db: AsyncSession,
    *,
    store_id: str,
    payment_id: str,
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> dict[str, JsonValue] | None:
    return await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="GET",
        path=f"/v1/payments/{payment_id}",
        configs=configs,
        persist_refresh=persist_refresh,
    )


async def search_mercadopago_payments(
    db: AsyncSession,
    *,
    store_id: str,
    external_reference: str,
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> list[dict[str, JsonValue]]:
    """Busca en Mercado Pago los pagos asociados a un turno.

    Se usa para conciliar cuando nunca llego el webhook o no pudimos aplicarlo:
    el ``external_reference`` es el id del turno, asi que alcanza para recuperar
    el cobro sin depender de la notificacion.
    """
    query = urlencode(
        {
            "external_reference": external_reference,
            "sort": "date_created",
            "criteria": "desc",
        }
    )
    response = await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="GET",
        path=f"/v1/payments/search?{query}",
        configs=configs,
        persist_refresh=persist_refresh,
    )
    if not response:
        return []
    results = response.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _resolve_amounts(
    service: Service,
    *,
    amount_override: Decimal | None,
    original_amount: Decimal | None,
    discount_amount: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Normaliza (importe, importe original, descuento) a 2 decimales.

    Cuatro parametros opcionales (amount_override / original_amount /
    discount_amount / keep_existing_amount) escondian cual importe gana. Aca
    queda explicito: manda el override y, si no hay, la sena del servicio.
    """
    amount = _money(
        Decimal(
            str(
                amount_override
                if amount_override is not None
                else calculate_service_payment_amount(service)
            )
        )
    )
    return (
        amount,
        _money(
            Decimal(str(original_amount if original_amount is not None else amount))
        ),
        _money(Decimal(str(discount_amount or 0))),
    )


def _reprice_existing_payment(
    payment: Payment,
    *,
    amount: Decimal,
    original_amount: Decimal,
    discount_amount: Decimal,
    promotion_code: str | None,
    keep_existing_amount: bool,
) -> bool:
    """Reaplica los importes a un cobro que ya existe. True si el importe cambio.

    Un cobro que ya nacio con la regla de sena (snapshot deposit_rule) no se
    re-tarifa por generar el link desde el panel: ese camino calcula la sena
    base del servicio y pisaba el monto a la mitad, dejaba el snapshot
    mintiendo y rompia la validacion de importe del webhook (el cliente pagaba
    y el turno no se confirmaba nunca). 2026-09-11.
    """
    conserva_importe = keep_existing_amount and payment.deposit_rule is not None
    if amount <= 0 or conserva_importe:
        return False
    if payment.is_accredited:
        # Un cobro acreditado no se re-tarifa: su importe es la plata que entro
        # (revision de perf/f4-pay, 2026-09-25).
        if payment.amount != amount:
            raise PaymentAlreadyAccreditedError()
        return False
    cambio = payment.amount != amount
    payment.amount = amount
    payment.original_amount = original_amount
    payment.discount_amount = discount_amount
    payment.promotion_code = promotion_code
    return cambio


def _retire_link(
    db: AsyncSession,
    payment: Payment,
    importes_del_link: ImportesDelLink | None = None,
) -> None:
    """El cobro deja de usar su link: queda un placeholder hasta el nuevo, y
    se olvida el pago de MP que tenia anotado (era del link retirado).

    Con ``MERCADOPAGO_LINK_REF_ENABLED`` tambien rota ``link_ref`` a un nonce
    que ningun link lleva: desde este momento un pago del link retirado no
    pasa la integridad, aunque llegue antes de que se selle el nuevo (entre la
    fase 1 y la 2 del link del panel). Sin esto el pago viejo se aplicaba en
    esa ventana y la fase 2 chocaba con la version del cobro (revision de
    perf/f4-pay, 2026-09-25).

    Un cobro acreditado nunca retira su link: conserva ``link_ref`` y
    ``external_payment_id`` para que un reembolso o contracargo posterior se
    reconozca como del link vigente y avise al dueno.
    """
    if payment.is_accredited:
        raise PaymentAlreadyAccreditedError()
    # Queda en el historial: un pago de este link que llegue despues (webhook
    # tardio o reentregado, o pagado antes de que MP lo venza) se reconoce y
    # se aplica o se alerta (``payments.links``).
    record_retired_link(db, payment, importes=importes_del_link)
    payment.preference_id, payment.payment_link = _placeholder_link(
        payment.appointment_id
    )
    # El id del pago de MP es de un intento sobre el link retirado: la
    # conciliacion y el rescate del job consultarian ese pago viejo en vez de
    # buscar los del link nuevo por su referencia (revision de perf/f4-pay).
    payment.external_payment_id = None
    if settings.MERCADOPAGO_LINK_REF_ENABLED:
        payment.link_ref = new_link_ref()


def _needs_provider_link(
    db: AsyncSession,
    payment: Payment,
    *,
    importe_cambio: bool,
    create_provider_link: bool,
    importes_del_link: ImportesDelLink | None = None,
) -> bool:
    """Hay que pedir un link nuevo a MP: cambio el importe o el que hay es falso.

    Si el importe cambio y el link no se pide ahora, el vigente (que cobra el
    importe VIEJO) se invalida a placeholder: la fase siguiente o un reintento
    lo ven y piden uno nuevo. Sin esto el cobro quedaba con el importe nuevo y
    el link de MP con el viejo, y el webhook rechazaba el pago por importe
    (misma clase que el bug del 2026-09-11).
    """
    if importe_cambio and not create_provider_link:
        _retire_link(db, payment, importes_del_link)
    return (
        importe_cambio
        or _is_placeholder_preference(payment.preference_id)
        or _is_placeholder_payment_link(payment.payment_link)
    )


def _expire_replaced_preference(
    db: AsyncSession, *, payment: Payment, previa: str | None
) -> None:
    """Manda a vencer en MP el link REAL que este cobro deja de usar (AUD2-B2-03).

    Publica ``payment.preference.expire``, que consume
    ``_claim_and_expire_preferences`` fuera de todo lock (B1-04). Hasta ahora
    solo lo publicaba ``release_pending``: los demas caminos que reemplazan un
    ``preference_id`` real (re-tarifar desde el panel, confirmar a mano con
    otro importe) dejaban vivo un checkout que Shifty ya no reconocia, y el
    pago de ese link se rechazaba por preferencia e importe hasta agotar los
    reintentos del inbox: plata en la cuenta de la tienda sin registro.

    Un placeholder no existe en Mercado Pago, asi que no se vence nada.
    """
    if not previa or _is_placeholder_preference(previa):
        return
    if payment.preference_id == previa:
        return
    db.add(
        OutboxMessage(
            store_id=payment.store_id,
            event_type=EVENT_PREFERENCE_EXPIRE,
            payload={
                "appointment_id": payment.appointment_id,
                "payment_id": payment.id,
                "preference_id": previa,
            },
        )
    )


def expire_live_charge(
    db: AsyncSession,
    payment: Payment | None,
    *,
    reason: str,
    released_by: str | None = None,
) -> Payment | None:
    """Vence el cobro vivo de un turno que se suelta; devuelve el cobro si lo vencio.

    Camino compartido que suelta un cobro vivo
    (``LIVE_CHARGE_PAYMENT_STATUSES``: ``pending`` o ``rejected``) cuando su
    turno se suelta (revision de perf/f4-pay, 2026-09-25). Lo usan cancelar,
    reprogramar y liberar desde el panel (``AppointmentService``), la
    cancelacion por bloqueo (``AppointmentBlockService``) y el webhook que
    suelta el turno (``processing._sync_appointment``). NO es el unico: el job
    de retenciones vencidas vence el cobro con ``stamp_payment_from_status``
    sin publicar el vencimiento, porque el link ya vencio solo en MP
    (``jobs._expired_holds_query``).

    Precondicion del llamador: el TURNO ya esta lockeado y ``payment`` se leyo
    despues (orden turno -> pago, regla 7). El estado lo cambia la entidad
    (``apply_status``: ``pending``/``rejected`` -> ``expired`` estan en el
    grafo) y el link de MP no se toca aca: se publica
    ``payment.preference.expire`` en la misma transaccion y el outbox lo vence
    despues del commit, sin lock (B1-04, regla 5). Un placeholder no existe en
    MP: no se publica nada.
    """
    if payment is None or not payment.is_live_charge:
        return None
    if not _is_placeholder_preference(payment.preference_id):
        db.add(
            OutboxMessage(
                store_id=payment.store_id,
                event_type=EVENT_PREFERENCE_EXPIRE,
                payload={
                    "appointment_id": payment.appointment_id,
                    "payment_id": payment.id,
                    "preference_id": payment.preference_id,
                },
            )
        )
    payment.apply_status(
        PaymentStatus.EXPIRED.value,
        payload={"reason": reason, "released_by": released_by},
    )
    return payment


class ProviderPreferenceWithoutLinkError(RuntimeError):
    """MP creo la preferencia pero no devolvio un link de checkout usable.

    La preferencia existe en MP con ese id: quien compensa la manda a vencer
    (revision de 7abb9b4..e5579b6, #7). Sigue siendo ``RuntimeError``: se
    responde como cualquier falla del proveedor.
    """

    def __init__(self, preference_id: str) -> None:
        super().__init__("Mercado Pago no devolvio una preferencia valida")
        self.preference_id = preference_id


async def _attach_provider_link(
    db: AsyncSession,
    *,
    payment: Payment,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount: Decimal,
) -> None:
    """Pide la preferencia a Mercado Pago y la sella en el cobro (sin commit).

    Quien la llama ya commiteo lo que retenia el lock (regla 5), pero las
    lecturas de aca (cobro, gateway, tienda, pagador) abrian OTRA transaccion
    que quedaba ``idle in transaction`` durante la request a MP, con el pool
    de 15 (F1-05, R8-05). Patron de AUD2-B2-08: se lee todo, commit PLANO de
    ``AsyncSession`` (el de ``TenantSession`` reaplica el contexto y reabre la
    transaccion en el acto), red, y se reaplica el contexto antes de volver a
    escribir. El commit plano tambien persiste lo que el llamador dejo
    pendiente en esta fase (re-tarifa, reapertura del cobro): ya estaba
    decidido y no depende de la respuesta de MP.

    Un 401 refresca el OAuth y lo persiste en su propia transaccion corta
    (``persist_gateway_refresh``), cerrada antes del segundo HTTP. Si MP falla,
    el contexto igual se reaplica: la compensacion del llamador escribe bajo
    RLS.
    """
    # Import diferido: jobs importa este modulo.
    from modules.payments.jobs import persist_gateway_refresh

    # Nonce propio de ESTE link (revision de perf/f4-pay): se sella con el
    # link; un pago de un link anterior ya no pasa la integridad.
    link_ref = new_link_ref() if settings.MERCADOPAGO_LINK_REF_ENABLED else None
    prepared = await prepare_mercadopago_preference(
        db,
        payment=payment,
        appointment=appointment,
        service=service,
        store_id=store_id,
        amount=amount,
        link_ref=link_ref,
    )
    preference_payload = None
    if prepared is not None:
        await AsyncSession.commit(db)
        try:
            preference_payload = await request_mercadopago_preference(
                db, prepared, persist_refresh=partial(persist_gateway_refresh, db)
            )
        finally:
            await _apply_tenant_context(db)
    if not preference_payload:
        raise PaymentGatewayNotConnectedError(
            "La tienda debe conectar su cuenta de Mercado Pago antes de cobrar"
        )
    preference_id = str(preference_payload.get("id") or "").strip()
    payment_link = _resolve_checkout_link(preference_payload)
    if not preference_id:
        raise RuntimeError("Mercado Pago no devolvio una preferencia valida")
    if not payment_link:
        raise ProviderPreferenceWithoutLinkError(preference_id)
    payment.preference_id = preference_id
    payment.payment_link = payment_link
    payment.link_ref = link_ref
    payment.raw_payload = preference_payload


def _nuevo_cobro_pendiente(
    *,
    store_id: str,
    appointment: Appointment,
    amount: Decimal,
    original_amount: Decimal,
    discount_amount: Decimal,
    promotion_code: str | None,
    deposit_rule: dict[str, JsonValue] | None,
) -> Payment:
    """Cobro PENDING con link placeholder: el real lo sella _attach_provider_link."""
    preference_id, payment_link = _placeholder_link(appointment.id)
    return Payment(
        store_id=store_id,
        appointment_id=appointment.id,
        amount=amount,
        original_amount=original_amount,
        discount_amount=discount_amount,
        currency="ARS",
        status=PaymentStatus.PENDING.value,
        preference_id=preference_id,
        payment_link=payment_link,
        promotion_code=promotion_code,
        deposit_rule=deposit_rule,
    )


async def ensure_payment_preference(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount_override: Decimal | None = None,
    original_amount: Decimal | None = None,
    discount_amount: Decimal | None = None,
    promotion_code: str | None = None,
    create_provider_link: bool = True,
    deposit_rule: dict[str, JsonValue] | None = None,
    keep_existing_amount: bool = False,
) -> Payment:
    payment, _creado = await _upsert_payment_preference(
        db,
        appointment=appointment,
        service=service,
        store_id=store_id,
        amount_override=amount_override,
        original_amount=original_amount,
        discount_amount=discount_amount,
        promotion_code=promotion_code,
        create_provider_link=create_provider_link,
        deposit_rule=deposit_rule,
        keep_existing_amount=keep_existing_amount,
    )
    return payment


def _refresh_existing_payment(
    db: AsyncSession,
    payment: Payment,
    *,
    amount: Decimal,
    original_amount: Decimal,
    discount_amount: Decimal,
    promotion_code: str | None,
    keep_existing_amount: bool,
    deposit_rule: dict[str, JsonValue] | None,
    create_provider_link: bool,
    renew_expired_link: bool,
) -> bool:
    """Reaplica importes y estado a un cobro que ya existe; True si hace falta
    pedirle un link nuevo a MP.

    ``renew_expired_link`` (solo la fase 1 del link del panel, revision de
    perf/f4-pay): un cobro ``expired`` pierde su link viejo y queda con un
    placeholder, asi la fase 2 pide uno NUEVO (y el viejo se manda a vencer,
    ``_expire_replaced_preference``). Antes se devolvia el link viejo, ya
    vencido. La reapertura del cobro la hace la fase 2, ya sellado el link.
    """
    # Lo que cobra el link vigente (importe, promo, descuento): si se
    # re-tarifa y se retira, el historial guarda los de ESE link, no los
    # nuevos.
    importes_del_link = ImportesDelLink.del_cobro(payment)
    importe_cambio = _reprice_existing_payment(
        payment,
        amount=amount,
        original_amount=original_amount,
        discount_amount=discount_amount,
        promotion_code=promotion_code,
        keep_existing_amount=keep_existing_amount,
    )
    if payment.is_accredited:
        # Ni se retira su link ni se pide uno nuevo (revision de perf/f4-pay).
        return False
    if deposit_rule is not None:
        payment.deposit_rule = deposit_rule
    if renew_expired_link and payment.status == PaymentStatus.EXPIRED.value:
        # Sin nonce por link no se reabre: ver
        # ``PaymentLinkRegenerationUnavailableError``.
        if not settings.MERCADOPAGO_LINK_REF_ENABLED:
            raise PaymentLinkRegenerationUnavailableError()
        _retire_link(db, payment, importes_del_link)
    # Reabrir solo si el grafo lo permite (lo decide la entidad): un pago
    # acreditado o devuelto no vuelve a pendiente por re-tarifarse.
    payment.apply_status(PaymentStatus.PENDING.value)
    return _needs_provider_link(
        db,
        payment,
        importes_del_link=importes_del_link,
        importe_cambio=importe_cambio,
        create_provider_link=create_provider_link,
    )


async def _upsert_payment_preference(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount_override: Decimal | None,
    original_amount: Decimal | None,
    discount_amount: Decimal | None,
    promotion_code: str | None,
    create_provider_link: bool,
    deposit_rule: dict[str, JsonValue] | None,
    keep_existing_amount: bool,
    renew_expired_link: bool = False,
) -> tuple[Payment, bool]:
    """ensure_payment_preference + si ESTA llamada inserto el cobro (S-17).

    ``renew_expired_link``: ver ``_refresh_existing_payment``.
    """
    amount, original_amount, discount_amount = _resolve_amounts(
        service,
        amount_override=amount_override,
        original_amount=original_amount,
        discount_amount=discount_amount,
    )
    result = await db.execute(
        select(Payment).where(
            Payment.appointment_id == appointment.id, Payment.store_id == store_id
        )
    )
    payment = result.scalar_one_or_none()
    creado = payment is None
    # Un id REAL que se deja de usar hay que vencerlo en MP (AUD2-B2-03).
    preferencia_previa = None if payment is None else payment.preference_id
    if payment:
        should_refresh_provider_link = _refresh_existing_payment(
            db,
            payment,
            amount=amount,
            original_amount=original_amount,
            discount_amount=discount_amount,
            promotion_code=promotion_code,
            keep_existing_amount=keep_existing_amount,
            deposit_rule=deposit_rule,
            create_provider_link=create_provider_link,
            renew_expired_link=renew_expired_link,
        )
    else:
        payment = _nuevo_cobro_pendiente(
            store_id=store_id,
            appointment=appointment,
            amount=amount,
            original_amount=original_amount,
            discount_amount=discount_amount,
            promotion_code=promotion_code,
            deposit_rule=deposit_rule,
        )
        db.add(payment)
        await db.flush()
        # Sin evento payment.preference.created: nadie lo consumia (B2-17).
        should_refresh_provider_link = True

    if create_provider_link and should_refresh_provider_link:
        await _attach_provider_link(
            db,
            payment=payment,
            appointment=appointment,
            service=service,
            store_id=store_id,
            amount=amount,
        )

    _expire_replaced_preference(db, payment=payment, previa=preferencia_previa)
    return payment, creado


async def _discard_orphan_payment(
    db: AsyncSession, *, store_id: str, payment_id: str, appointment_id: str
) -> None:
    """Compensacion: borra el cobro que creo la fase 1 y lo que encolo para el.

    Solo para un cobro que nacio en ESTA llamada (nadie mas lo referencia): si
    MP fallo, dejarlo PENDING con placeholder inflaba pending_payments y
    total_pending_amount de la conciliacion y el job lo consultaba a MP en
    cada corrida. Transaccion propia, como _revert_failed_booking en
    public_api.

    Solo borra si el cobro sigue con el link placeholder: si otra request
    concurrente ya le sello un link real, el cobro es de ella y queda (S-17).

    No borra ningun evento del outbox: la fase 1 no publica ninguno. Habia un
    DELETE de ``payment.preference.created`` que no borraba nunca nada porque
    ese evento dejo de publicarse en B2-17, el mismo dia que se escribio esta
    compensacion; leerlo sugeria un evento vivo que no existe (AUD2-B2-12,
    2026-09-20). Lo garantiza
    tests/integration/test_eventos_de_pago_con_consumidor.py.
    """
    placeholder, _ = _placeholder_link(appointment_id)
    await db.execute(
        delete(Payment).where(
            Payment.id == payment_id,
            Payment.store_id == store_id,
            Payment.preference_id == placeholder,
        )
    )
    await db.commit()


# Estados de un turno cuyo horario ya se SOLTO: un cobro no puede quedar vivo
# ni nacer sobre ellos (el link apuntaria a un turno que ya no existe) y un
# pago que llega despues no lo revive (el horario pudo tomarlo otra persona;
# S-16, 2026-09-19). Unica fuente: la usan el link del panel, la confirmacion
# manual y el webhook. ``completed`` y ``absent`` NO estan: cobrar despues de
# atender es un flujo real (correccion de alcance del coordinador,
# revision de perf/f4-pay 2026-09-25).
RELEASED_APPOINTMENT_STATUSES: frozenset[str] = frozenset(
    {
        AppointmentStatus.CANCELLED.value,
        AppointmentStatus.EXPIRED.value,
    }
)


class PaymentAlreadyAccreditedError(AppException):
    """409 neutro: el cobro ya esta acreditado y no se re-tarifa ni cambia de
    link (revision de perf/f4-pay, 2026-09-25)."""

    def __init__(self) -> None:
        super().__init__(
            message="El cobro ya esta acreditado",
            http_status=409,
            error_code="PAYMENT_ALREADY_ACCREDITED",
        )


class PaymentLinkRegenerationUnavailableError(AppException):
    """409 neutro: regenerar el link de un cobro vencido no esta disponible.

    Sin ``MERCADOPAGO_LINK_REF_ENABLED`` el link nuevo tendria la misma
    ``external_reference`` que el viejo y un pago tardio del viejo se
    aplicaria al cobro reabierto con el nuevo vivo: pago doble. Asi esta rama
    nunca abre esa ventana, aunque operaciones apague el flag.
    """

    def __init__(self) -> None:
        super().__init__(
            message="Por ahora no se puede generar un link nuevo para este cobro",
            http_status=409,
            error_code="PAYMENT_LINK_REGENERATION_UNAVAILABLE",
        )


class AppointmentNotPayableError(AppException):
    """409 neutro: el turno ya no admite un cobro."""

    def __init__(self) -> None:
        super().__init__(
            message="El turno ya no admite un cobro",
            http_status=409,
            error_code="APPOINTMENT_NOT_PAYABLE",
        )


async def lock_payable_appointment(
    db: AsyncSession, *, appointment_id: str, store_id: str
) -> bool:
    """Lockea el turno (``FOR UPDATE``) y dice si admite un cobro: existe y
    no esta soltado (``RELEASED_APPOINTMENT_STATUSES``).

    Es el PRIMER lock de quien toca el cobro del turno (orden turno -> pago,
    regla 7), el mismo que cancelar, liberar y el webhook. Lee la columna, no
    la entidad: el turno que trae el router se leyo sin lock y puede estar
    viejo. Sin autoflush: un cambio pendiente del cobro no puede tomar la fila
    del pago antes que la del turno.
    """
    with db.no_autoflush:
        estado = (
            await db.execute(
                select(Appointment.status)
                .where(
                    Appointment.id == appointment_id,
                    Appointment.store_id == store_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
    return estado is not None and estado not in RELEASED_APPOINTMENT_STATUSES


async def _discard_unsealed_link(
    db: AsyncSession,
    *,
    store_id: str,
    appointment_id: str,
    payment_id: str,
    preference_id: str | None,
) -> None:
    """El turno se solto mientras MP creaba el link: no se sella y se vence.

    Transaccion propia, despues del rollback de la fase 2: el link existe en
    Mercado Pago y nadie lo va a registrar, asi que se manda a vencer por el
    outbox (``payment.preference.expire``, sin lock ni llamada en el request).
    """
    if preference_id and not _is_placeholder_preference(preference_id):
        db.add(
            OutboxMessage(
                store_id=store_id,
                event_type=EVENT_PREFERENCE_EXPIRE,
                payload={
                    "appointment_id": appointment_id,
                    "payment_id": payment_id,
                    "preference_id": preference_id,
                },
            )
        )
        await db.commit()


async def _drop_unsealed_link(
    db: AsyncSession,
    nueva: str | None,
    previa: str | None,
    ids: tuple[str, str, str],
) -> None:
    """Rollback de la fase 2 y vencimiento del link que ESTA llamada creo.

    Revision de perf/f4-pay (2026-09-25): si la fase 2 no puede sellar (el
    turno se solto, o otra escritura choco con la version del cobro), la
    preferencia que MP ya creo quedaba viva sin que nadie la registrara. Un
    link igual a ``previa`` no lo creo esta llamada: no se toca. ``nueva`` se
    lee ANTES del flush (uno fallido expira la instancia) e ``ids`` (tienda,
    cobro, turno) antes de la fase 2.
    """
    store_id, payment_id, appointment_id = ids
    await db.rollback()
    if nueva != previa:
        await _discard_unsealed_link(
            db,
            store_id=store_id,
            appointment_id=appointment_id,
            payment_id=payment_id,
            preference_id=nueva,
        )


async def _drop_unsealed_link_or_log(
    db: AsyncSession,
    nueva: str | None,
    previa: str | None,
    ids: tuple[str, str, str],
) -> None:
    """``_drop_unsealed_link`` sin tapar el error del llamador.

    Revision de 7abb9b4..e5579b6 (#7): si vencer el link falla (base caida al
    commitear el outbox), ese fallo reemplazaba al error que se estaba
    compensando (el choque de version o el 409 del turno soltado). Ahora queda
    en el log y en Sentry, con la preferencia para vencerla a mano, y el
    llamador sigue con SU error.
    """
    try:
        await _drop_unsealed_link(db, nueva, previa, ids)
    except Exception as exc:
        store_id, payment_id, _ = ids
        await _unsealed_expire_failed(
            db, exc, store_id=store_id, payment_id=payment_id, preference_id=nueva
        )


async def expire_unsealed_preference(
    db: AsyncSession,
    *,
    store_id: str,
    appointment_id: str,
    payment_id: str,
    preference_id: str,
) -> None:
    """Manda a vencer una preferencia que MP creo y nadie va a registrar.

    Para quien ya compenso (rollback o reserva revertida): publica
    ``payment.preference.expire`` en su propia transaccion y NUNCA levanta;
    un fallo queda en el log y en Sentry y el llamador sigue con su error.
    Lo usa la reserva publica cuando MP devuelve una preferencia sin link de
    checkout (seguimiento del #7 de la revision de 7abb9b4..e5579b6).
    """
    try:
        await _discard_unsealed_link(
            db,
            store_id=store_id,
            appointment_id=appointment_id,
            payment_id=payment_id,
            preference_id=preference_id,
        )
    except Exception as exc:
        await _unsealed_expire_failed(
            db,
            exc,
            store_id=store_id,
            payment_id=payment_id,
            preference_id=preference_id,
        )


async def _unsealed_expire_failed(
    db: AsyncSession,
    exc: Exception,
    *,
    store_id: str,
    payment_id: str,
    preference_id: str | None,
) -> None:
    """Log y Sentry con la preferencia (para vencerla a mano) y rollback
    best-effort: la sesion puede haber quedado con un commit fallido."""
    contexto = {
        "store_id": store_id,
        "payment_id": payment_id,
        "preference_id": preference_id,
    }
    logger.exception("unsealed_preference_expire_failed", **contexto)
    report_exception(exc, **contexto)
    with suppress(Exception):
        await db.rollback()


async def _panel_link_phase_one(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount_override: Decimal | None,
) -> tuple[Payment, bool]:
    """Fase 1 del link del panel, SIN commit: turno lockeado primero (regla
    7), 409 si esta soltado, y el cobro persistido (re-tarifado si
    corresponde; un cobro ``expired`` pierde su link viejo).

    "Lo cree yo" sale del INSERT mismo, no de un SELECT previo (S-17,
    2026-09-19): entre ese SELECT y el de la fase 1 otra request podia
    commitear el cobro; esta lo tomaba por propio y, si su fase 2 chocaba con
    la de la otra, borraba un cobro ajeno (rafaga -> cero cobros).
    """
    if not await lock_payable_appointment(
        db, appointment_id=appointment.id, store_id=store_id
    ):
        await db.rollback()
        raise AppointmentNotPayableError()
    try:
        return await _upsert_payment_preference(
            db,
            appointment=appointment,
            service=service,
            store_id=store_id,
            amount_override=amount_override,
            original_amount=None,
            discount_amount=None,
            promotion_code=None,
            create_provider_link=False,
            deposit_rule=None,
            keep_existing_amount=True,
            renew_expired_link=True,
        )
    except PaymentLinkRegenerationUnavailableError, PaymentAlreadyAccreditedError:
        await db.rollback()  # suelta el lock del turno sin escribir nada
        raise


async def _panel_link_from_provider(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    payment: Payment,
) -> Payment:
    """Fase 2 del link del panel hasta MP: pide y sella el link (sin commit)
    con el importe que dejo la fase 1, dentro del presupuesto del request."""
    with mercadopago_budget(settings.MERCADOPAGO_REQUEST_BUDGET_SECONDS):
        return await ensure_payment_preference(
            db,
            appointment=appointment,
            service=service,
            store_id=store_id,
            amount_override=payment.amount,
            original_amount=payment.original_amount,
            discount_amount=payment.discount_amount,
            promotion_code=payment.promotion_code,
            keep_existing_amount=True,
            create_provider_link=True,
        )


async def create_panel_payment_preference(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount_override: Decimal | None = None,
) -> Payment:
    """Link de pago pedido desde el panel: commit -> llamada -> compensacion.

    Fase 1 (``_panel_link_phase_one``): se persiste el cobro y se COMMITEA.
    Fase 2: con la transaccion cerrada se llama a Mercado Pago (regla 5) y se
    sella el link real. Si MP falla y el cobro lo creo esta llamada, se borra
    (compensacion); si ya existia, queda con su placeholder.

    Las dos fases lockean el turno antes de escribir el cobro (orden turno ->
    pago, regla 7) y rechazan un turno soltado
    (``RELEASED_APPOINTMENT_STATUSES``) con 409 ``APPOINTMENT_NOT_PAYABLE``.
    Si se solto mientras MP respondia, el link nuevo no se sella y se manda a
    vencer. Un cobro ``expired`` con link NUEVO recien sellado se reabre con
    ``Payment.reopen_for_panel_link`` (unico llamador; revision de
    perf/f4-pay, 2026-09-25).
    """
    payment, creado = await _panel_link_phase_one(
        db,
        appointment=appointment,
        service=service,
        store_id=store_id,
        amount_override=amount_override,
    )
    # Leidos antes del commit: tras un rollback las instancias quedan
    # expiradas y leerlas de nuevo seria IO fuera de lugar. ``previa``: el
    # link que dejo la fase 1; uno distinto despues lo creo ESTA llamada.
    ids = (store_id, payment.id, appointment.id)
    previa = payment.preference_id
    await db.commit()
    return await _panel_link_phase_two(
        db,
        appointment=appointment,
        service=service,
        payment=payment,
        creado=creado,
        ids=ids,
        previa=previa,
    )


async def _panel_link_phase_two(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    payment: Payment,
    creado: bool,
    ids: tuple[str, str, str],
    previa: str | None,
) -> Payment:
    """Fase 2 del link del panel, con la fase 1 ya commiteada: MP, sellado
    bajo el lock del turno y las compensaciones de cada falla.

    ``ids``: (tienda, cobro, turno), leidos antes del commit de la fase 1.
    Ningun camino de falla deja viva en MP una preferencia que ESTA llamada
    creo y no sello: la del choque de version, la del turno soltado y la que
    MP devolvio sin link de checkout (revision de 7abb9b4..e5579b6, #7).
    """
    store_id, payment_id, appointment_id = ids
    nueva = previa
    try:
        payment = await _panel_link_from_provider(
            db,
            appointment=appointment,
            service=service,
            store_id=store_id,
            payment=payment,
        )
        nueva = payment.preference_id  # antes del flush: si falla, se expira
        sellable = await lock_payable_appointment(
            db, appointment_id=appointment_id, store_id=store_id
        )
        if sellable:
            # Turno lockeado y no soltado: el cobro vencido vuelve a ser vivo.
            payment.reopen_for_panel_link()
            await db.commit()
    except (RuntimeError, CircuitBreakerOpenError) as exc:
        # Fallo del PROVEEDOR (MercadoPagoAPIError es RuntimeError): si el
        # cobro lo inserto esta llamada, se compensa borrandolo. Si MP llego a
        # crear la preferencia (respuesta sin init_point), se vence.
        await db.rollback()
        if creado:
            await _discard_orphan_payment(
                db,
                store_id=store_id,
                payment_id=payment_id,
                appointment_id=appointment_id,
            )
        if isinstance(exc, ProviderPreferenceWithoutLinkError):
            await _drop_unsealed_link_or_log(db, exc.preference_id, previa, ids)
        raise
    except Exception:
        # Conflicto de concurrencia (StaleDataError, IntegrityError): otra
        # request esta trabajando sobre el mismo cobro. No se borra el cobro,
        # pero el link que MP ya creo no puede quedar vivo.
        await _drop_unsealed_link_or_log(db, nueva, previa, ids)
        raise
    if not sellable:
        await _drop_unsealed_link_or_log(db, nueva, previa, ids)
        raise AppointmentNotPayableError()
    await db.refresh(payment)
    return payment


def sync_appointment_with_payment(
    appointment: Appointment, payment_status: str
) -> None:
    if payment_status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }:
        if appointment.status in {
            AppointmentStatus.PENDING.value,
            AppointmentStatus.PENDING_PAYMENT.value,
        }:
            appointment.apply_status_transition(AppointmentStatus.CONFIRMED)
        return

    if payment_status == PaymentStatus.REFUNDED.value:
        # Decision explicita, no omision:
        #
        # - Si el turno todavia esperaba el cobro, el reembolso lo deja sin
        #   sustento y se cancela.
        # - Si el turno YA estaba confirmado, se mantiene confirmado. La tienda
        #   devolvio la sena pero eso no implica que no vaya a atender: cancelar
        #   por su cuenta sorprenderia al cliente con un turno perdido. Si la
        #   tienda tambien quiere soltar el horario, tiene cancel() para eso.
        if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
            appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        return

    if payment_status in {PaymentStatus.REJECTED.value, PaymentStatus.EXPIRED.value}:
        if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
            appointment.apply_status_transition(AppointmentStatus.EXPIRED)


def stamp_payment_from_status(
    payment: Payment,
    payment_status: str,
    *,
    payload: dict[str, JsonValue] | None = None,
) -> bool:
    # El grafo decide: una transicion ilegal se ignora (el webhook se reentrega
    # y no queremos romper por un duplicado), pero nunca se aplica. La regla y la
    # mutacion viven en la entidad (Payment.apply_status); esto es solo el wrapper
    # que conservan los llamadores (router, webhook, conciliacion).
    #
    # Devuelve si la transicion se aplico: el llamador que escribe otros campos
    # del cobro (el external_payment_id del webhook) tiene que enterarse de que
    # la entidad la descarto (AUD2-B2-05).
    return payment.apply_status(payment_status, payload=payload)
