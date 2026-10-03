"""Por donde se cobra la sena de una reserva.

Decision de Mateo (2026-10-03): una sena OBLIGATORIA se paga por Mercado Pago
o por WhatsApp (transferencia o efectivo coordinados en el chat). Cuando el
cliente paga por WhatsApp, el personal de la tienda confirma el pago a mano
desde el panel (``PaymentService.manual_confirm``).

Una tienda que pide una sena obligatoria tiene que tener al menos un canal:

- ``mercadopago``: los cobros online prendidos (flag ``payments``) y una
  cuenta de Mercado Pago conectada (``payments.service.mercadopago_connected``,
  el mismo predicado que usa la preferencia);
- ``whatsapp``: un WhatsApp de la tienda que se pueda convertir en link de
  wa.me (``core.whatsapp_phone``, la misma regla que el boton del front).

Se exige al configurar la sena (``services.service.ServiceCatalogService``) y
otra vez al reservar (``resolve_deposit_channel``): la tienda puede borrar su
WhatsApp, apagar los cobros o desconectar MP despues, y un turno que nunca se
podria pagar no se crea (409 ``DEPOSIT_CHANNEL_UNAVAILABLE``). Cuando eso pasa
la tienda se entera dos veces: al perder el ultimo canal
(``warn_if_deposit_channel_lost``, aviso al panel y por mail) y cuando un
cliente rebota (``report_deposit_channel_unavailable``, log y Sentry).

Una sena por WhatsApp se representa igual que la de MP: turno
``pending_payment`` y un ``Payment`` ``pending`` con link placeholder. Lo
distingue ``Payment.provider = "manual"``: sin link ni consulta a MP, vence
directo por el grafo. Su retencion es otra (``whatsapp_hold_deadline``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, StoreNotFoundException, ValidationException
from core.feature_flags import is_store_feature_enabled
from core.observability import OncePer, report_exception
from core.utils import ensure_utc_aware, now_utc
from core.whatsapp_phone import normalize_phone_for_whatsapp
from modules.notifications.model import NotificationType
from modules.payments.model import (
    PAYMENT_PROVIDER_MANUAL,
    PAYMENT_PROVIDER_MERCADOPAGO,
    OutboxMessage,
)
from modules.payments.service import _get_store, mercadopago_connected
from modules.services.model import Service
from modules.stores.model import Store

logger = structlog.get_logger()

DepositChannel = Literal["mercadopago", "whatsapp"]

# ---------------------------------------------------------------------------
# Retencion de una sena por WhatsApp (decision de Mateo, 2026-10-03)
# ---------------------------------------------------------------------------
# La de MP es corta (``PAYMENT_HOLD_MINUTES``, 30): el cliente paga en el
# checkout al toque. Por WhatsApp hay una persona del otro lado que tiene que
# leer el chat y pasar los datos, y el cliente transferir: 30 minutos dejaba
# afuera a quien reservaba de noche (revision 4R de la PR #108). El turno se
# retiene hasta ``WHATSAPP_HOLD_LEAD`` antes de que empiece, para que si se
# libera alguien mas alcance a tomarlo.
WHATSAPP_HOLD_LEAD = timedelta(hours=2)
# Piso: si el turno empieza tan pronto que ``inicio - LEAD`` ya paso o cae en
# menos de esto, el cliente igual tiene esta ventana (la misma que MP) para
# pagar, nunca mas alla del inicio del turno.
WHATSAPP_MIN_HOLD = timedelta(minutes=30)


def whatsapp_hold_deadline(
    starts_at: datetime, *, now: datetime | None = None
) -> datetime:
    """Hasta cuando se retiene un turno con la sena por WhatsApp pendiente.

    ``inicio - WHATSAPP_HOLD_LEAD``; si eso cae antes de ``ahora +
    WHATSAPP_MIN_HOLD``, ``ahora + WHATSAPP_MIN_HOLD``; y nunca despues del
    inicio. Dos horas son un intervalo absoluto, no un dia de calendario: la
    resta en UTC es la correcta (regla 24). Devuelve un instante UTC aware;
    la hora argentina es presentacion (el mail, el aviso y la pantalla).
    """
    inicio = ensure_utc_aware(starts_at)
    ahora = ensure_utc_aware(now) if now is not None else now_utc()
    plazo = inicio - WHATSAPP_HOLD_LEAD
    piso = ahora + WHATSAPP_MIN_HOLD
    if plazo < piso:
        plazo = min(piso, inicio)
    return plazo


# ---------------------------------------------------------------------------
# Canales
# ---------------------------------------------------------------------------


def provider_for(channel: DepositChannel) -> str:
    """``Payment.provider`` del cobro de una sena que se paga por ``channel``."""
    if channel == "whatsapp":
        return PAYMENT_PROVIDER_MANUAL
    return PAYMENT_PROVIDER_MERCADOPAGO


def deposit_mode_of(service: object) -> str:
    """Modo de sena del servicio (``none`` si no tiene)."""
    return str(getattr(service, "deposit_mode", "none") or "none")


@dataclass(frozen=True)
class DepositChannels:
    """Canales con los que la tienda puede cobrar una sena hoy, y el flag de
    cobros online (``payments``), que tambien decide ``auto`` sin sena
    obligatoria."""

    mercadopago: bool
    whatsapp: bool
    payments_enabled: bool

    @property
    def any(self) -> bool:
        return self.mercadopago or self.whatsapp


class DepositChannelUnavailableError(AppException):
    """409 al reservar: la sena es obligatoria y la tienda no tiene con que
    cobrarla. Mensaje neutro (regla 20): no dice que le falta a la tienda."""

    def __init__(self) -> None:
        super().__init__(
            message=(
                "Este negocio no puede cobrar la seña de este servicio en este "
                "momento. Comunicate con el negocio para reservar."
            ),
            http_status=status.HTTP_409_CONFLICT,
            error_code="DEPOSIT_CHANNEL_UNAVAILABLE",
        )


class DepositChannelRequiredError(AppException):
    """422 al configurar una sena obligatoria sin canal (panel del dueno)."""

    def __init__(self) -> None:
        super().__init__(
            message=(
                "Para pedir una seña obligatoria, conectá Mercado Pago (con los "
                "cobros online activos) o cargá en Configuración un WhatsApp "
                "válido del negocio (con código de área). Sin uno de los dos, "
                "el cliente no tiene cómo pagarla."
            ),
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code="DEPOSIT_CHANNEL_REQUIRED",
        )


async def deposit_channels_of(db: AsyncSession, store: Store) -> DepositChannels:
    """Los canales de la tienda. Una consulta (la de MP) solo si el flag de
    cobros esta prendido."""
    payments_enabled = is_store_feature_enabled(store.feature_flags, "payments")
    mercadopago = payments_enabled and await mercadopago_connected(db, store.id)
    whatsapp = normalize_phone_for_whatsapp(store.whatsapp_number) is not None
    return DepositChannels(
        mercadopago=mercadopago,
        whatsapp=whatsapp,
        payments_enabled=payments_enabled,
    )


async def deposit_channels_for(
    db: AsyncSession, store: Store, *, deposit_mode: str
) -> DepositChannels:
    """Los canales que importan para un servicio con este modo de sena.

    Atajo: los canales solo deciden una sena OBLIGATORIA, asi que para el
    resto no se consulta la config de MP (una lectura menos en cada reserva y
    en cada preview); se informan sin canales y con el flag, que es lo unico
    que ``resolve_deposit_channel`` mira en ese caso.
    """
    if deposit_mode == "required":
        return await deposit_channels_of(db, store)
    return DepositChannels(
        mercadopago=False,
        whatsapp=False,
        payments_enabled=is_store_feature_enabled(store.feature_flags, "payments"),
    )


async def require_deposit_channel(db: AsyncSession, store_id: str) -> None:
    """Configurar una sena obligatoria exige un canal (422 si no hay)."""
    store = await _get_store(db, store_id)
    if store is None:
        raise StoreNotFoundException()
    if not (await deposit_channels_of(db, store)).any:
        raise DepositChannelRequiredError()


def _whatsapp_usable(
    channels: DepositChannels, allow_manual_coordination: bool
) -> bool:
    """WhatsApp cobra la sena si la tienda lo tiene y, cuando tambien hay MP,
    acepta coordinar por fuera. ``allow_manual_coordination`` en falso solo
    obliga a pagar online cuando se puede: sin MP no deja a nadie sin canal
    (mismo criterio que tenia ``online_payment_mandatory``)."""
    return channels.whatsapp and (allow_manual_coordination or not channels.mercadopago)


def online_payment_mandatory(
    *,
    channels: DepositChannels,
    deposit_amount: Decimal,
    deposit_mode: str,
    allow_manual_coordination: bool,
) -> bool:
    """La sena obligatoria solo se puede pagar por Mercado Pago."""
    return (
        deposit_mode == "required"
        and deposit_amount > 0
        and channels.mercadopago
        and not _whatsapp_usable(channels, allow_manual_coordination)
    )


def _explicit_mercadopago(*, payments_enabled: bool, deposit_amount: Decimal) -> None:
    if deposit_amount <= 0:
        raise ValidationException(
            "Este servicio no tiene una seña configurada para Mercado Pago"
        )
    if not payments_enabled:
        raise ValidationException(
            "La tienda no tiene habilitados los cobros con Mercado Pago"
        )


def _required_deposit_channel(
    payment_method: str, channels: DepositChannels, allow_manual_coordination: bool
) -> DepositChannel:
    whatsapp = _whatsapp_usable(channels, allow_manual_coordination)
    if payment_method == "manual":
        if whatsapp:
            return "whatsapp"
        if channels.mercadopago:
            raise ValidationException(
                "Este servicio requiere pagar la seña con Mercado Pago para reservar"
            )
        raise DepositChannelUnavailableError()
    if channels.mercadopago:
        return "mercadopago"
    if whatsapp:
        return "whatsapp"
    raise DepositChannelUnavailableError()


def resolve_deposit_channel(
    payment_method: str,
    *,
    channels: DepositChannels,
    deposit_amount: Decimal,
    deposit_mode: str,
    allow_manual_coordination: bool,
) -> DepositChannel | None:
    """Por donde se cobra la sena de esta reserva, o ``None`` si no se cobra.

    - ``mercadopago`` pedido explicito: igual que siempre (la seña y el flag;
      la cuenta sin conectar es el 409 ``PAYMENT_GATEWAY_NOT_CONNECTED`` al
      pedir el link).
    - Sin sena obligatoria (``optional``, ``none`` o importe 0): lo de
      siempre; ``auto`` cobra por MP si los cobros estan prendidos.
    - Sena obligatoria: ``auto`` prefiere MP y si no WhatsApp; ``manual`` es
      WhatsApp. Sin canal, 409 ``DEPOSIT_CHANNEL_UNAVAILABLE``.

    Puede levantar ``ValidationException`` si el metodo pedido no es viable.
    """
    if payment_method == "mercadopago":
        _explicit_mercadopago(
            payments_enabled=channels.payments_enabled, deposit_amount=deposit_amount
        )
        return "mercadopago"
    if deposit_amount <= 0:
        return None
    if deposit_mode != "required":
        auto_online = payment_method == "auto" and channels.payments_enabled
        return "mercadopago" if auto_online else None
    return _required_deposit_channel(
        payment_method, channels, allow_manual_coordination
    )


# ---------------------------------------------------------------------------
# Observabilidad: la tienda se quedo sin canal (revision 4R de la PR #108, W2)
# ---------------------------------------------------------------------------

# Un cliente que rebota con 409 ``DEPOSIT_CHANNEL_UNAVAILABLE`` deja un
# warning con ids y un evento a Sentry, a lo sumo uno por tienda cada
# ``_ALERT_EVERY_SECONDS`` y proceso: una rafaga de reintentos no inunda el log
# y el 409, que el dueno no ve, no queda en silencio. La misma ventana para los
# dos (re-revision de la PR #108: el "una vez por tienda" de Sentry era un set
# que solo crecia y avisaba una sola vez en la vida del proceso).
_ALERT_EVERY_SECONDS = 3600.0
_alertas = OncePer(_ALERT_EVERY_SECONDS)


class DepositChannelUnavailableAlert(RuntimeError):
    """Para Sentry: una tienda pide sena obligatoria y no tiene con que
    cobrarla (``report_deposit_channel_unavailable``)."""


def report_deposit_channel_unavailable(
    *, store_id: str, service_id: str, clock: float | None = None
) -> None:
    """Deja rastro de una reserva rechazada por falta de canal de cobro."""
    if not _alertas.allow(store_id, now=clock):
        return
    logger.warning(
        "deposit_channel_unavailable", store_id=store_id, service_id=service_id
    )
    report_exception(
        DepositChannelUnavailableAlert("sena obligatoria sin canal de cobro"),
        store_id=store_id,
        service_id=service_id,
    )


async def _has_required_deposit_services(db: AsyncSession, store_id: str) -> bool:
    found = await db.scalar(
        select(Service.id)
        .where(
            Service.store_id == store_id,
            Service.is_active.is_(True),
            Service.deposit_mode == "required",
        )
        .limit(1)
    )
    return found is not None


async def warn_if_deposit_channel_lost(
    db: AsyncSession, store: Store, before: DepositChannels
) -> bool:
    """Avisa al dueno si este cambio le saco el ULTIMO canal de cobro.

    Lo llaman los tres caminos que pueden sacarlo, con ``before`` leido antes
    del cambio y la sesion ya con el cambio aplicado (sin commit): editar la
    tienda (el WhatsApp), apagar los cobros online y desconectar MP. Si tenia
    canal, ya no tiene y le quedan servicios activos con sena obligatoria,
    publica ``store.deposit_channel_lost`` al outbox en la misma transaccion:
    el lote lo vuelve aviso del panel y mail a los admins despues del commit.

    Un aviso y no un bloqueo (eleccion tecnica del coordinador): sacar el
    WhatsApp o desconectar MP puede ser justo lo que la tienda necesita (un
    numero que cambio, una cuenta comprometida), y frenarlo la dejaria con un
    canal que no quiere. Lo que queda frenado es la reserva (409), y el aviso
    le dice como arreglarlo. Devuelve si aviso.
    """
    if not before.any:
        return False
    if (await deposit_channels_of(db, store)).any:
        return False
    if not await _has_required_deposit_services(db, store.id):
        return False
    logger.warning("deposit_channel_lost", store_id=store.id)
    db.add(
        OutboxMessage(
            store_id=store.id,
            event_type=NotificationType.DEPOSIT_CHANNEL_LOST.value,
            payload={"store_id": store.id},
        )
    )
    return True
