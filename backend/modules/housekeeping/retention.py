"""Retencion de datos operativos: purga diaria por lotes (F1-19).

R3-03 / R7-07 (plan de rendimiento, 2026-09-24): nada purgaba el outbox, el
inbox de webhooks, los OTP ni las notificaciones (solo ``auth_sessions``
tenia su job). A 6.000 turnos/dia son ~10 GB/ano, y cada lote del beat paga
el bloat de su tabla.

Las ventanas las decidio el dueno (decision 17; CLAUDE.md §1: la IA no
decide destruccion) y viven en settings:

- ``outbox_messages`` y ``webhook_inbox`` PROCESADOS hace mas de
  ``RETENTION_OUTBOX_PROCESSED_DAYS`` / ``RETENTION_INBOX_PROCESSED_DAYS``
  (90). Un pendiente (``processed_at`` NULL) no se toca nunca, y tampoco un
  reclamo de vencimiento de link de MP en curso, que tiene ``processed_at``
  provisorio (``PREFERENCE_EXPIRE_CLAIM``).
- ``otp_verifications`` vencidos hace mas de ``RETENTION_OTP_EXPIRED_DAYS``
  (7). La verificacion vale 30 minutos (``is_client_contact_verified``).
- ``notifications`` LEIDAS hace mas de ``RETENTION_NOTIFICATIONS_READ_DAYS``
  (180). Una sin leer no se toca.
- ``audit_logs`` NUNCA: es evidencia; se archiva fuera de la base.

Por lotes de ``RETENTION_BATCH_SIZE`` con un commit por lote: ningun lock
largo ni una transaccion gigante, y cortar entre lotes no pierde lo hecho.
Con presupuesto de tiempo por debajo del soft time limit de Celery: lo que no
entra queda para el dia siguiente. ``dry_run`` (o ``RETENTION_DRY_RUN``) solo
cuenta, con una sentencia agregada por tabla.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.config import settings
from modules.notifications.model import Notification
from modules.otp.model import OtpVerification
from modules.payments.jobs import PREFERENCE_EXPIRE_CLAIM, exclusive_job
from modules.payments.model import OutboxMessage, WebhookInbox

logger = structlog.get_logger()

RETENTION_JOB_LOCK = "job:purge_expired_data"
# Holgado bajo el soft time limit (120 s): se mira antes de cada lote y un
# lote de 5.000 borra en fracciones de segundo con el indice de su filtro.
RETENTION_TIME_BUDGET_SECONDS = 90.0


def _reloj() -> float:
    """Reloj del presupuesto; los tests lo reemplazan."""
    return time.monotonic()


@dataclass(frozen=True)
class _Regla:
    tabla: str
    modelo: Any
    vencido: Callable[[datetime], ColumnElement[bool]]


def _outbox_vencido(now: datetime) -> ColumnElement[bool]:
    limite = now - timedelta(days=settings.RETENTION_OUTBOX_PROCESSED_DAYS)
    return and_(
        OutboxMessage.processed_at.is_not(None),
        OutboxMessage.processed_at < limite,
        or_(
            OutboxMessage.error.is_(None),
            OutboxMessage.error != PREFERENCE_EXPIRE_CLAIM,
        ),
    )


def _inbox_vencido(now: datetime) -> ColumnElement[bool]:
    limite = now - timedelta(days=settings.RETENTION_INBOX_PROCESSED_DAYS)
    return and_(
        WebhookInbox.processed_at.is_not(None),
        WebhookInbox.processed_at < limite,
    )


def _otp_vencido(now: datetime) -> ColumnElement[bool]:
    limite = now - timedelta(days=settings.RETENTION_OTP_EXPIRED_DAYS)
    return OtpVerification.expires_at < limite


def _aviso_vencido(now: datetime) -> ColumnElement[bool]:
    limite = now - timedelta(days=settings.RETENTION_NOTIFICATIONS_READ_DAYS)
    return and_(Notification.read_at.is_not(None), Notification.read_at < limite)


REGLAS: tuple[_Regla, ...] = (
    _Regla("outbox_messages", OutboxMessage, _outbox_vencido),
    _Regla("webhook_inbox", WebhookInbox, _inbox_vencido),
    _Regla("otp_verifications", OtpVerification, _otp_vencido),
    _Regla("notifications", Notification, _aviso_vencido),
)


def _en_cero() -> dict[str, int]:
    return {regla.tabla: 0 for regla in REGLAS}


async def purge_expired_data(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    dry_run: bool | None = None,
) -> dict[str, int]:
    """Filas borradas (o que se borrarian, en ``dry_run``) por tabla.

    Una corrida a la vez: advisory lock de sesion, como los jobs de pagos,
    que sobrevive a los commits por lote. El contexto de tenant (bypass) lo
    pone la tarea.
    """
    now = now or datetime.now(timezone.utc)
    solo_contar = settings.RETENTION_DRY_RUN if dry_run is None else dry_run
    async with exclusive_job(db, RETENTION_JOB_LOCK) as tomado:
        if not tomado:
            logger.info("purge_expired_data_overlap_skipped")
            return _en_cero()
        if solo_contar:
            return await _contar(db, now)
        return await _borrar(db, now)


async def _contar(db: AsyncSession, now: datetime) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for regla in REGLAS:
        conteo[regla.tabla] = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(regla.modelo)
                    .where(regla.vencido(now))
                )
            ).scalar_one()
        )
    await db.commit()
    return conteo


async def _borrar(db: AsyncSession, now: datetime) -> dict[str, int]:
    borradas = _en_cero()
    lote = settings.RETENTION_BATCH_SIZE
    limite = _reloj() + RETENTION_TIME_BUDGET_SECONDS
    for regla in REGLAS:
        while True:
            if _reloj() >= limite:
                logger.warning(
                    "purge_expired_data_budget_exhausted",
                    tabla=regla.tabla,
                    budget_seconds=RETENTION_TIME_BUDGET_SECONDS,
                    **borradas,
                )
                return borradas
            # Postgres no tiene DELETE ... LIMIT: el lote sale de la subconsulta.
            ids = select(regla.modelo.id).where(regla.vencido(now)).limit(lote)
            resultado = await db.execute(
                delete(regla.modelo)
                .where(regla.modelo.id.in_(ids))
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            cuantas = int(getattr(resultado, "rowcount", 0) or 0)
            borradas[regla.tabla] += cuantas
            if cuantas < lote:
                break
    return borradas


__all__ = [
    "REGLAS",
    "RETENTION_JOB_LOCK",
    "RETENTION_TIME_BUDGET_SECONDS",
    "purge_expired_data",
]
