"""Lectura y avance del ciclo de vida de la suscripcion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import Select, select, tuple_
from sqlalchemy import true as sa_true
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

logger = structlog.get_logger()


# Recorrido del ciclo diario (AUD2-B2-09). El tamano de pagina es el viejo
# ``limit``; lo que cambio es que ya no es un TOPE sino el paso de un cursor
# que recorre todas las suscripciones activas. El techo de paginas acota la
# corrida (regla 9: nada sin cota) y se registra si se alcanza, para que un
# corte nunca vuelva a ser invisible.
SUBSCRIPTION_PAGE_SIZE = 500
SUBSCRIPTION_MAX_PAGES = 40


def today_local(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(ARGENTINA_TZ).date()


async def get_active_subscription(
    db: AsyncSession, store_id: str
) -> StoreSubscription | None:
    # ``= true`` y no ``IS true``: el indice parcial
    # uq_store_subscriptions_active_store es ``WHERE is_active = true`` y
    # Postgres no prueba que ``IS true`` lo implique; con ``IS`` leia todo el
    # historial de la tienda en cada escritura del panel (F1-17, R7-09).
    result = await db.execute(
        select(StoreSubscription)
        .where(
            StoreSubscription.store_id == store_id,
            StoreSubscription.is_active == sa_true(),
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
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = SUBSCRIPTION_PAGE_SIZE,
) -> DailyRun:
    """Un paso del ciclo diario. NO commitea: eso es de la tarea.

    Recorre TODAS las suscripciones activas en paginas de ``limit``. Antes
    ``limit`` era un tope: con mas de 500 activas, cada corrida volvia a
    mirar las mismas 500 mas viejas (ya al dia) y las de mas atras no se
    avisaban, no pasaban a ``past_due`` y no se suspendian nunca, sin que
    nada lo registrara (AUD2-B2-09, 2026-09-20).

    Los avisos se devuelven para que la tarea los publique al outbox; aca no
    se manda ningun mail.

    Costo declarado (V-diff, 2026-09-20): la corrida entera es UNA
    transaccion, y cada pagina toma sus filas con ``FOR UPDATE SKIP LOCKED``
    que no se sueltan hasta el commit de la tarea. En el peor caso quedan
    bloqueadas ``SUBSCRIPTION_MAX_PAGES * limit`` filas (40 x 500 = 20.000)
    durante toda la corrida. Con las tiendas de hoy no muerde; si en
    produccion las suscripciones activas pasan de unos cientos, conviene que
    la TAREA (``billing/tasks.py``) commitee por pagina en vez de al final,
    para que el lock de cada pagina dure lo que dura esa pagina. No esta
    implementado a proposito: cambia la unidad de trabajo de la tarea y eso
    se decide con datos, no por anticipado.
    """
    now = now or datetime.now(timezone.utc)
    hoy = today_local(now)
    run = DailyRun()
    cursor: tuple[datetime, str] | None = None
    for pagina in range(SUBSCRIPTION_MAX_PAGES):
        filas = list((await db.execute(_pagina(cursor, limit))).scalars().all())
        if not filas:
            return run
        for subscription in filas:
            _aplicar_accion_diaria(subscription, run, hoy=hoy, now=now)
        # Cursor por clave, no por OFFSET: ``skip_locked`` saltea filas y un
        # OFFSET se correria justo esa cantidad, dejando huecos.
        ultima = filas[-1]
        cursor = (ultima.created_at, ultima.id)
    logger.warning(
        "subscription_lifecycle_pages_exhausted",
        pages=pagina + 1,
        inspected=run.inspected,
    )
    return run


def _pagina(
    cursor: tuple[datetime, str] | None, limit: int
) -> Select[tuple[StoreSubscription]]:
    """Una pagina del recorrido, ordenada por ``(created_at, id)``.

    ``id`` desempata: con ``created_at`` repetido el orden seria arbitrario y
    el cursor podria saltearse filas o repetirlas.
    """
    consulta = select(StoreSubscription).where(StoreSubscription.is_active.is_(True))
    if cursor is not None:
        consulta = consulta.where(
            tuple_(StoreSubscription.created_at, StoreSubscription.id) > cursor
        )
    return (
        consulta.order_by(
            StoreSubscription.created_at.asc(), StoreSubscription.id.asc()
        )
        .limit(limit)
        # Dos corridas solapadas no toman la misma fila.
        .with_for_update(skip_locked=True)
    )


def _aplicar_accion_diaria(
    subscription: StoreSubscription, run: DailyRun, *, hoy: date, now: datetime
) -> None:
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
