from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class GatewayConfigUpsert(BaseModel):
    provider: str = Field(default="mercadopago", pattern=r"^(mercadopago|stripe)$")
    access_token: str | None = Field(None, min_length=3, max_length=500)
    public_key: str | None = Field(None, max_length=255)
    webhook_secret: str | None = Field(None, max_length=255)


class GatewayConfigResponse(BaseModel):
    provider: str
    configured: bool
    public_key: str | None = None
    access_token_masked: str | None = None
    connection_mode: str | None = None
    oauth_user_id: str | None = None
    oauth_connected_at: datetime | None = None
    oauth_supported: bool = False


class MercadoPagoOAuthStartResponse(BaseModel):
    auth_url: str
    qr_url: str
    expires_at: datetime


class PaymentPreferenceResponse(BaseModel):
    payment_public_id: str
    appointment_id: str
    amount: Decimal
    currency: str
    preference_id: str | None
    payment_link: str | None
    status: str


# Techo alineado con services.price (le=10_000_000) y con Numeric(12, 2) en la
# base: un monto sin limite superior desborda la columna y termina en un 500.
class ManualPaymentRequest(BaseModel):
    amount: Decimal | None = Field(
        None, ge=0, le=10_000_000, max_digits=12, decimal_places=2
    )
    notes: str | None = Field(None, max_length=500)


class RefundRequest(BaseModel):
    amount: Decimal | None = Field(
        None, ge=0, le=10_000_000, max_digits=12, decimal_places=2
    )
    reason: str | None = Field(None, max_length=500)
    manual: bool = False


class PaymentResponse(BaseModel):
    public_id: str
    appointment_id: str
    amount: Decimal
    currency: str
    status: str
    paid_at: datetime | None = None

    class Config:
        from_attributes = True


class OAuthDisconnectResponse(BaseModel):
    """Resultado de dar de baja la conexion con Mercado Pago.

    Devuelve un modelo, no un dict crudo: el router canonico envuelve la
    respuesta en {success, data} y un dict con su propia clave 'success'
    rompia la validacion, dejando el endpoint en 500.
    """

    disconnected: bool


class OutboxProcessResponse(BaseModel):
    processed: int
    failed: int
    inspected: int


class OutboxStatsResponse(BaseModel):
    pending: int
    pending_with_error: int
    processed: int


class ReconciliationSummaryResponse(BaseModel):
    pending_payments: int
    approved_payments: int
    rejected_payments: int
    manual_confirmed_payments: int
    refunded_payments: int
    total_pending_amount: Decimal
    total_approved_amount: Decimal
    pending_webhooks: int
    failed_webhooks: int
    pending_outbox: int
