"""Por donde se cobra la sena de una reserva.

Decision de Mateo (2026-10-03): una sena OBLIGATORIA se paga por Mercado Pago
o por WhatsApp (transferencia o efectivo coordinados en el chat). Cuando el
cliente paga por WhatsApp, el personal de la tienda confirma el pago a mano
desde el panel (``PaymentService.manual_confirm``).

Una tienda que pide una sena obligatoria tiene que tener al menos un canal:

- ``mercadopago``: los cobros online prendidos (flag ``payments``) y una
  cuenta de Mercado Pago conectada (``payment_gateway_configs`` con token);
- ``whatsapp``: un WhatsApp de la tienda que se pueda convertir en link de
  wa.me (``core.whatsapp_phone``, la misma regla que el boton del front).

Se exige al configurar la sena (``services.service.ServiceCatalogService``) y
otra vez al reservar (``resolve_deposit_channel``): la tienda puede borrar su
WhatsApp, apagar los cobros o desconectar MP despues, y un turno que nunca se
podria pagar no se crea (409 ``DEPOSIT_CHANNEL_UNAVAILABLE``).

Una sena por WhatsApp se representa igual que la de MP: turno
``pending_payment`` con la misma retencion y un ``Payment`` ``pending`` con
link placeholder. Lo distingue ``Payment.provider = "manual"``, que el job de
retenciones vencidas y la conciliacion ya saltean para no consultar a MP.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, ValidationException
from core.feature_flags import is_store_feature_enabled
from core.whatsapp_phone import normalize_phone_for_whatsapp
from modules.payments.model import PaymentGatewayConfig
from modules.stores.model import Store

DepositChannel = Literal["mercadopago", "whatsapp"]

# Proveedor del ``Payment`` de una sena que se cobra por fuera (WhatsApp) y
# se confirma a mano: ``Payment.provider`` (default ``mercadopago``).
MANUAL_PAYMENT_PROVIDER = "manual"


@dataclass(frozen=True)
class DepositChannels:
    """Canales con los que la tienda puede cobrar una sena hoy."""

    mercadopago: bool
    whatsapp: bool

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
                "cobros online activos) o cargá el WhatsApp del negocio en "
                "Configuración. Sin uno de los dos, el cliente no tiene cómo "
                "pagarla."
            ),
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="DEPOSIT_CHANNEL_REQUIRED",
        )


async def _mercadopago_connected(db: AsyncSession, store_id: str) -> bool:
    """La tienda tiene una cuenta de MP con token guardado."""
    found = await db.scalar(
        select(PaymentGatewayConfig.id)
        .where(
            PaymentGatewayConfig.store_id == store_id,
            PaymentGatewayConfig.provider == "mercadopago",
            PaymentGatewayConfig.encrypted_access_token != "",
        )
        .limit(1)
    )
    return found is not None


async def deposit_channels_of(db: AsyncSession, store: Store) -> DepositChannels:
    """Los canales de la tienda. Una consulta (la de MP) solo si el flag de
    cobros esta prendido."""
    mercadopago = is_store_feature_enabled(
        store.feature_flags, "payments"
    ) and await _mercadopago_connected(db, store.id)
    whatsapp = normalize_phone_for_whatsapp(store.whatsapp_number) is not None
    return DepositChannels(mercadopago=mercadopago, whatsapp=whatsapp)


async def require_deposit_channel(db: AsyncSession, store: Store) -> None:
    """Configurar una sena obligatoria exige un canal (422 si no hay)."""
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
    payments_enabled: bool,
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
            payments_enabled=payments_enabled, deposit_amount=deposit_amount
        )
        return "mercadopago"
    if deposit_amount <= 0:
        return None
    if deposit_mode != "required":
        auto_online = payment_method == "auto" and payments_enabled
        return "mercadopago" if auto_online else None
    return _required_deposit_channel(
        payment_method, channels, allow_manual_coordination
    )
