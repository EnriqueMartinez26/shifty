"""Ciclo de vida de la suscripcion de una tienda. Logica pura.

Estados: ``active`` -> ``past_due`` (vencio el periodo) -> ``suspended``
(se agoto la gracia); ``cancelled`` es terminal. Reasignar un plan desde el
superadmin vuelve a ``active``. Espejo del grafo de pagos: la transicion se
aplica por ``apply_subscription_transition`` y el CHECK de la base rechaza
cualquier otro valor.

Que significa "suspendida" (decision de producto 2026-09-10): se esconde la
pagina publica y se bloquean las escrituras del panel; el login y la lectura
siguen para que el dueno pueda ver el aviso y pagar.

La aritmetica es de calendario en hora argentina: "vence en 3 dias" se
cuenta en dias locales, no en bloques de 24 horas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from core.utils import ARGENTINA_TZ, ensure_utc_aware

SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_PAST_DUE = "past_due"
SUBSCRIPTION_SUSPENDED = "suspended"
SUBSCRIPTION_CANCELLED = "cancelled"

SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_SUSPENDED,
    SUBSCRIPTION_CANCELLED,
)

ALLOWED_SUBSCRIPTION_TRANSITIONS: dict[str, set[str]] = {
    SUBSCRIPTION_ACTIVE: {SUBSCRIPTION_PAST_DUE, SUBSCRIPTION_CANCELLED},
    SUBSCRIPTION_PAST_DUE: {
        SUBSCRIPTION_ACTIVE,
        SUBSCRIPTION_SUSPENDED,
        SUBSCRIPTION_CANCELLED,
    },
    SUBSCRIPTION_SUSPENDED: {SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELLED},
    SUBSCRIPTION_CANCELLED: {SUBSCRIPTION_ACTIVE},
}

# Dias de aviso antes del vencimiento y dias de gracia despues.
SUBSCRIPTION_WARN_DAYS = 7
SUBSCRIPTION_GRACE_DAYS = 7


class InvalidSubscriptionTransition(ValueError):
    pass


def apply_subscription_transition(subscription: Any, new_status: str) -> None:
    current = str(subscription.status)
    if new_status == current:
        return
    if new_status not in ALLOWED_SUBSCRIPTION_TRANSITIONS.get(current, set()):
        raise InvalidSubscriptionTransition(
            f"Transicion de suscripcion invalida: {current} -> {new_status}"
        )
    subscription.status = new_status


def local_day(instant: datetime) -> date:
    return ensure_utc_aware(instant).astimezone(ARGENTINA_TZ).date()


@dataclass(frozen=True)
class SubscriptionOutlook:
    status: str
    period_end_day: date | None
    days_left: int | None
    grace_until_day: date | None
    warn: bool
    blocks_writes: bool

    @property
    def public_page_hidden(self) -> bool:
        return self.blocks_writes


def outlook(subscription: Any | None, *, today: date) -> SubscriptionOutlook:
    """Que ve el dueno hoy: estado, dias restantes y si esta suspendida."""
    if subscription is None:
        return SubscriptionOutlook(
            status="none",
            period_end_day=None,
            days_left=None,
            grace_until_day=None,
            warn=False,
            blocks_writes=False,
        )
    status = str(subscription.status)
    period_end = getattr(subscription, "current_period_end", None)
    end_day = local_day(period_end) if period_end else None
    days_left = (end_day - today).days if end_day else None
    grace_until = end_day + timedelta(days=SUBSCRIPTION_GRACE_DAYS) if end_day else None
    warn = (
        status == SUBSCRIPTION_ACTIVE
        and days_left is not None
        and 0 <= days_left <= SUBSCRIPTION_WARN_DAYS
    )
    return SubscriptionOutlook(
        status=status,
        period_end_day=end_day,
        days_left=days_left,
        grace_until_day=grace_until,
        warn=warn,
        blocks_writes=status == SUBSCRIPTION_SUSPENDED,
    )


@dataclass(frozen=True)
class DailyAction:
    """Que le corresponde a una suscripcion en la corrida diaria."""

    new_status: str | None = None
    send_warning: bool = False


def daily_action(subscription: Any, *, today: date) -> DailyAction:
    status = str(subscription.status)
    period_end = getattr(subscription, "current_period_end", None)
    if period_end is None or status == SUBSCRIPTION_CANCELLED:
        return DailyAction()
    end_day = local_day(period_end)
    if status == SUBSCRIPTION_ACTIVE:
        if today > end_day:
            return DailyAction(new_status=SUBSCRIPTION_PAST_DUE)
        ya_avisada = getattr(subscription, "expiry_warning_sent_at", None) is not None
        if not ya_avisada and (end_day - today).days <= SUBSCRIPTION_WARN_DAYS:
            return DailyAction(send_warning=True)
        return DailyAction()
    if status == SUBSCRIPTION_PAST_DUE:
        if today > end_day + timedelta(days=SUBSCRIPTION_GRACE_DAYS):
            return DailyAction(new_status=SUBSCRIPTION_SUSPENDED)
        return DailyAction()
    return DailyAction()
