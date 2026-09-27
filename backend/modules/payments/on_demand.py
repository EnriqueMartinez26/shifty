"""Conciliacion a demanda de UN cobro desde el poll publico (F1-21).

"Pague y sigue pendiente" (R9-09, decision 20): si el webhook de Mercado Pago
no llego o no se pudo aplicar, el cliente veia "pendiente" hasta el beat de
la conciliacion (5-6 min) mientras su pagina consultaba el estado cada 2 s.
Cuando el poll ve un cobro de MP pendiente hace mas de 20 s pide conciliar
ESE cobro, como mucho una vez cada 15 s por cobro: el ``SET NX EX`` en el
Redis de estado deduplica entre polls, pestanas y replicas.

Sin Redis no se pide nada: sin la deduplicacion cada poll (uno cada 2 s por
cliente) seria una consulta a MP. La conciliacion general sigue de red.

Revision de f2b (2026-09-24):

- Solo entre los 20 s y ``RECONCILIATION_MIN_AGE_MINUTES``: despues el cobro
  ya entra en la conciliacion general y pedirlo aparte duplica la consulta.
- La tarea se publica con ``expires=15``: si el worker esta atrasado, vence
  en la cola en vez de correr tarde; el poll la vuelve a pedir.
- Va a la cola ``celery`` (la de los lotes), no a ``interactive``: una
  consulta a MP puede tardar hasta el timeout del cliente HTTP y ``interactive``
  tiene un solo proceso para los OTP.
- El reintento corto del inbox tras un webhook fallido tambien se deduplica,
  por tienda y cada 30 s: una rafaga de webhooks rotos no encola una tarea
  por webhook.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from redis.asyncio import Redis

from core.config import settings
from core.enqueue import enqueue
from core.redis import REDIS_UNAVAILABLE_ERRORS
from core.utils import ensure_utc_aware
from modules.payments.model import Payment, PaymentStatus
from modules.payments.tasks import (
    process_payment_webhook_inbox,
    reconcile_payment_on_demand,
)

logger = structlog.get_logger()

ON_DEMAND_MIN_PENDING = timedelta(seconds=20)
ON_DEMAND_DEDUP_SECONDS = 15
ON_DEMAND_TASK_EXPIRES_SECONDS = 15
_DEDUP_KEY = "payments:reconcile-now:{payment_id}"

INBOX_RETRY_COUNTDOWN_SECONDS = 15
INBOX_RETRY_DEDUP_SECONDS = 30
_INBOX_RETRY_KEY = "payments:inbox-retry:{store_id}"


def wants_on_demand_reconciliation(
    payment: Payment, *, now: datetime | None = None
) -> bool:
    """Cobro de MP pendiente entre 20 s y la edad minima de la conciliacion."""
    if payment.provider != "mercadopago":
        return False
    if payment.status != PaymentStatus.PENDING.value:
        return False
    now = now or datetime.now(timezone.utc)
    edad = now - ensure_utc_aware(payment.created_at)
    cubierto_por_el_lote = timedelta(minutes=settings.RECONCILIATION_MIN_AGE_MINUTES)
    return ON_DEMAND_MIN_PENDING <= edad < cubierto_por_el_lote


async def _primero_en_la_ventana(redis: Redis, clave: str, segundos: int) -> bool:
    """``SET NX EX``: True solo para el primero de la ventana. Sin Redis, False."""
    try:
        return bool(await redis.set(clave, "1", nx=True, ex=segundos))
    except REDIS_UNAVAILABLE_ERRORS as exc:
        logger.warning("payments_dedup_skipped", error_type=type(exc).__name__)
        return False


async def request_on_demand_reconciliation(redis: Redis, payment_id: str) -> bool:
    """Encola la conciliacion del cobro si nadie la pidio en los ultimos 15 s."""
    clave = _DEDUP_KEY.format(payment_id=payment_id)
    if not await _primero_en_la_ventana(redis, clave, ON_DEMAND_DEDUP_SECONDS):
        return False
    return await enqueue(
        reconcile_payment_on_demand,
        payment_id,
        options={"expires": ON_DEMAND_TASK_EXPIRES_SECONDS},
    )


async def request_inbox_retry(redis: Redis, store_id: str) -> bool:
    """Reintento corto del inbox tras un webhook fallido (F1-21), uno cada 30 s
    por tienda."""
    clave = _INBOX_RETRY_KEY.format(store_id=store_id)
    if not await _primero_en_la_ventana(redis, clave, INBOX_RETRY_DEDUP_SECONDS):
        return False
    return await enqueue(
        process_payment_webhook_inbox,
        options={"countdown": INBOX_RETRY_COUNTDOWN_SECONDS},
    )


__all__ = [
    "ON_DEMAND_DEDUP_SECONDS",
    "ON_DEMAND_MIN_PENDING",
    "request_inbox_retry",
    "request_on_demand_reconciliation",
    "wants_on_demand_reconciliation",
]
