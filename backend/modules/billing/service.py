"""Lectura y avance del ciclo de vida de la suscripcion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ARGENTINA_TZ
from modules.billing.model import StoreSubscription
from modules.billing.subscription_rules import (
    SUBSCRIPTION_SUSPENDED,
    SubscriptionOutlook,
    apply_subscription_transition,
    daily_action,
    outlook,
)


def today_local(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(ARGENTINA_TZ).date()


async def get_active_subscription(
    db: AsyncSession, store_id: str
) -> StoreSubscription | None:
    result = await db.execute(
        select(StoreSubscription)
        .where(
            StoreSubscription.store_id == store_id,
            StoreSubscription.is_active.is_(True),
        )
        .order_by(StoreSubscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def store_outlook(
    db: AsyncSession, store_id: str, *, now: datetime | None = None
) -> SubscriptionOutlook:
    subscription = await get_active_subscription(db, store_id)
    return outlook(subscription, today=today_local(now))


async def store_is_suspended(db: AsyncSession, store_id: str) -> bool:
    """Una tienda suspendida no escribe en el panel ni se muestra al publico."""
    subscription = await get_active_subscription(db, store_id)
    return bool(
        subscription is not None and subscription.status == SUBSCRIPTION_SUSPENDED
    )


@dataclass
class DailyRun:
    inspected: int = 0
    past_due: int = 0
    suspended: int = 0
    warned: int = 0
    # (store_id, dias restantes, nombre del plan) para el aviso al dueno.
    warnings: list[tuple[str, int, str]] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        return {
            "inspected": self.inspected,
            "past_due": self.past_due,
            "suspended": self.suspended,
            "warned": self.warned,
        }


async def advance_subscriptions(
    db: AsyncSession, *, now: datetime | None = None, limit: int = 500
) -> DailyRun:
    """Un paso del ciclo diario. NO commitea: eso es de la tarea.

    Los avisos se devuelven para que la tarea los publique al outbox; aca no
    se manda ningun mail.
    """
    now = now or datetime.now(timezone.utc)
    hoy = today_local(now)
    rows = await db.execute(
        select(StoreSubscription)
        .where(StoreSubscription.is_active.is_(True))
        .order_by(StoreSubscription.created_at.asc())
        .limit(limit)
        # Dos corridas solapadas no toman la misma fila.
        .with_for_update(skip_locked=True)
    )
    run = DailyRun()
    for subscription in rows.scalars().all():
        run.inspected += 1
        accion = daily_action(subscription, today=hoy)
        if accion.new_status:
            apply_subscription_transition(subscription, accion.new_status)
            if accion.new_status == SUBSCRIPTION_SUSPENDED:
                run.suspended += 1
            else:
                run.past_due += 1
        elif accion.send_warning:
            subscription.expiry_warning_sent_at = now
            vista = outlook(subscription, today=hoy)
            run.warnings.append(
                (
                    subscription.store_id,
                    int(vista.days_left or 0),
                    subscription.plan_name or "tu plan",
                )
            )
            run.warned += 1
    return run
