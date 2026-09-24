"""Conciliacion a demanda de UN cobro desde el poll publico (F1-21).

"Pague y sigue pendiente" (R9-09, decision 20): si el webhook de Mercado Pago
no llego o no se pudo aplicar, el cliente veia "pendiente" hasta el beat de
la conciliacion (5-6 min) mientras su pagina consultaba el estado cada 2 s.
Cuando el poll ve un cobro de MP pendiente hace mas de 20 s pide conciliar
ESE cobro, como mucho una vez cada 15 s por cobro: el ``SET NX EX`` en el
Redis de estado deduplica entre polls, pestanas y replicas.

Sin Redis no se pide nada: sin la deduplicacion cada poll (uno cada 2 s por
cliente) seria una consulta a MP. La conciliacion general sigue de red.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from redis.asyncio import Redis

from core.enqueue import enqueue
from core.redis import REDIS_UNAVAILABLE_ERRORS
from core.utils import ensure_utc_aware
from modules.payments.model import Payment, PaymentStatus
from modules.payments.tasks import reconcile_payment_on_demand

logger = structlog.get_logger()

ON_DEMAND_MIN_PENDING = timedelta(seconds=20)
ON_DEMAND_DEDUP_SECONDS = 15
_DEDUP_KEY = "payments:reconcile-now:{payment_id}"


def wants_on_demand_reconciliation(
    payment: Payment, *, now: datetime | None = None
) -> bool:
    """Cobro de MP que sigue pendiente mas de 20 s despues de creado."""
    if payment.provider != "mercadopago":
        return False
    if payment.status != PaymentStatus.PENDING.value:
        return False
    now = now or datetime.now(timezone.utc)
    return now - ensure_utc_aware(payment.created_at) >= ON_DEMAND_MIN_PENDING


async def request_on_demand_reconciliation(redis: Redis, payment_id: str) -> bool:
    """Encola la conciliacion del cobro si nadie la pidio en los ultimos 15 s."""
    try:
        tomado = await redis.set(
            _DEDUP_KEY.format(payment_id=payment_id),
            "1",
            nx=True,
            ex=ON_DEMAND_DEDUP_SECONDS,
        )
    except REDIS_UNAVAILABLE_ERRORS as exc:
        logger.warning(
            "on_demand_reconciliation_skipped", error_type=type(exc).__name__
        )
        return False
    if not tomado:
        return False
    return await enqueue(reconcile_payment_on_demand, payment_id)


__all__ = [
    "ON_DEMAND_DEDUP_SECONDS",
    "ON_DEMAND_MIN_PENDING",
    "request_on_demand_reconciliation",
    "wants_on_demand_reconciliation",
]
