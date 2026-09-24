"""Retencion: purga diaria por lotes de lo operativo que ya cumplio su funcion.

F1-19 (plan de rendimiento, R3-03 y R7-07, decision 17 del dueno,
2026-09-24). Nada purgaba ``outbox_messages``, ``webhook_inbox``,
``otp_verifications`` ni ``notifications``: ~10 GB/ano a 6.000 turnos/dia, con
el bloat de cada tabla pagado en cada lote del beat. Ventanas decididas por
el dueno (no por la IA, CLAUDE.md §1):

- outbox e inbox PROCESADOS hace mas de 90 dias;
- OTP vencidos hace mas de 7 dias;
- notificaciones LEIDAS hace mas de 180 dias;
- ``audit_logs`` nunca (es evidencia: se archiva, no se borra).

Nunca se toca un pendiente: un outbox o inbox sin ``processed_at``, un
reclamo de vencimiento de link de MP en curso, una notificacion sin leer.
Lotes de ``RETENTION_BATCH_SIZE`` con un commit por lote, y modo de prueba
(``dry_run``) que solo cuenta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.housekeeping.retention as retention
from core.config import settings
from modules.audit.model import AuditLog
from modules.notifications.model import Notification
from modules.otp.model import OtpVerification
from modules.payments.jobs import PREFERENCE_EXPIRE_CLAIM
from modules.payments.model import OutboxMessage, WebhookInbox

AHORA = datetime(2026, 9, 24, 4, 30, tzinfo=timezone.utc)


def _hace(dias: float) -> datetime:
    return AHORA - timedelta(days=dias)


def _outbox(**campos: Any) -> OutboxMessage:
    return OutboxMessage(store_id="t-ret", event_type="x", payload={}, **campos)


def _inbox(clave: str, **campos: Any) -> WebhookInbox:
    return WebhookInbox(store_id="t-ret", event_id=clave, payload={}, **campos)


def _otp(vence: datetime) -> OtpVerification:
    return OtpVerification(
        store_id="t-ret", phone="+5491100000000", code_hash="h", expires_at=vence
    )


def _aviso(**campos: Any) -> Notification:
    return Notification(store_id="t-ret", type="x", title="t", **campos)


async def _sembrar(session: AsyncSession) -> None:
    session.add_all(
        [
            # Outbox: se va solo el procesado viejo.
            _outbox(created_at=_hace(100), processed_at=_hace(95)),
            _outbox(created_at=_hace(20), processed_at=_hace(10)),
            _outbox(created_at=_hace(200)),  # pendiente viejo: intocable
            _outbox(
                created_at=_hace(200),
                processed_at=_hace(100),
                error=PREFERENCE_EXPIRE_CLAIM,
            ),  # reclamo en curso: intocable
            # Inbox: igual.
            _inbox("viejo", created_at=_hace(100), processed_at=_hace(95)),
            _inbox("reciente", created_at=_hace(20), processed_at=_hace(10)),
            _inbox("pendiente", created_at=_hace(200)),
            # OTP: vencidos hace mas de 7 dias.
            _otp(_hace(8)),
            _otp(_hace(3)),
            _otp(AHORA + timedelta(minutes=5)),
            # Notificaciones: leidas hace mas de 180 dias.
            _aviso(created_at=_hace(300), read_at=_hace(200)),
            _aviso(created_at=_hace(300), read_at=_hace(10)),
            _aviso(created_at=_hace(300)),  # sin leer: intocable
            # Auditoria: nunca.
            AuditLog(
                created_at=_hace(4000),
                resource_type="Appointment",
                resource_id="x",
                action="update",
            ),
        ]
    )
    await session.commit()


async def _cuantos(session: AsyncSession, modelo: Any) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(modelo))).scalar_one()
    )


@pytest.mark.asyncio
async def test_purga_solo_lo_vencido_y_nunca_pendientes_ni_auditoria(
    test_session: AsyncSession,
) -> None:
    await _sembrar(test_session)

    resultado = await retention.purge_expired_data(test_session, now=AHORA)

    assert resultado == {
        "outbox_messages": 1,
        "webhook_inbox": 1,
        "otp_verifications": 1,
        "notifications": 1,
    }
    assert await _cuantos(test_session, OutboxMessage) == 3
    assert await _cuantos(test_session, WebhookInbox) == 2
    assert await _cuantos(test_session, OtpVerification) == 2
    assert await _cuantos(test_session, Notification) == 2
    assert await _cuantos(test_session, AuditLog) == 1
    pendientes = (
        await test_session.execute(
            select(func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.processed_at.is_(None))
        )
    ).scalar_one()
    assert pendientes == 1


@pytest.mark.asyncio
async def test_el_modo_de_prueba_cuenta_sin_borrar(test_session: AsyncSession) -> None:
    await _sembrar(test_session)

    resultado = await retention.purge_expired_data(
        test_session, now=AHORA, dry_run=True
    )

    assert resultado == {
        "outbox_messages": 1,
        "webhook_inbox": 1,
        "otp_verifications": 1,
        "notifications": 1,
    }
    assert await _cuantos(test_session, OutboxMessage) == 4
    assert await _cuantos(test_session, Notification) == 3


@pytest.mark.asyncio
async def test_borra_por_lotes_con_un_commit_por_lote(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(5):
        test_session.add(_outbox(created_at=_hace(100), processed_at=_hace(95)))
    await test_session.commit()
    monkeypatch.setattr(settings, "RETENTION_BATCH_SIZE", 2)
    commits: list[int] = []
    commit_original = test_session.commit

    async def commit_contado() -> None:
        commits.append(1)
        await commit_original()

    monkeypatch.setattr(test_session, "commit", commit_contado)

    resultado = await retention.purge_expired_data(test_session, now=AHORA)

    assert resultado["outbox_messages"] == 5
    # 2 + 2 + 1 en outbox, y un lote vacio en cada una de las otras tres.
    assert len(commits) == 3 + 3
    assert await _cuantos(test_session, OutboxMessage) == 0


def test_las_ventanas_son_las_que_decidio_el_dueno() -> None:
    assert settings.RETENTION_OUTBOX_PROCESSED_DAYS == 90
    assert settings.RETENTION_INBOX_PROCESSED_DAYS == 90
    assert settings.RETENTION_OTP_EXPIRED_DAYS == 7
    assert settings.RETENTION_NOTIFICATIONS_READ_DAYS == 180
    assert settings.RETENTION_BATCH_SIZE == 5000
    assert settings.RETENTION_DRY_RUN is False


@pytest.mark.asyncio
async def test_una_corrida_a_la_vez(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    pedidos: list[str] = []

    @asynccontextmanager
    async def ocupado(_db: object, nombre: str) -> AsyncIterator[bool]:
        pedidos.append(nombre)
        yield False

    monkeypatch.setattr(retention, "exclusive_job", ocupado)
    await _sembrar(test_session)

    resultado = await retention.purge_expired_data(test_session, now=AHORA)

    assert pedidos == ["job:purge_expired_data"]
    assert resultado == {
        "outbox_messages": 0,
        "webhook_inbox": 0,
        "otp_verifications": 0,
        "notifications": 0,
    }
    assert await _cuantos(test_session, OutboxMessage) == 4


@pytest.mark.asyncio
async def test_con_el_presupuesto_agotado_deja_el_resto_para_manana(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cada lote queda commiteado: cortar entre lotes no pierde nada."""
    for _ in range(5):
        test_session.add(_outbox(created_at=_hace(100), processed_at=_hace(95)))
    await test_session.commit()
    monkeypatch.setattr(settings, "RETENTION_BATCH_SIZE", 2)
    reloj = {"ahora": 0.0}

    def reloj_falso() -> float:
        # Cada consulta del reloj "tarda" medio presupuesto.
        valor = reloj["ahora"]
        reloj["ahora"] += retention.RETENTION_TIME_BUDGET_SECONDS / 2
        return valor

    monkeypatch.setattr(retention, "_reloj", reloj_falso)

    resultado = await retention.purge_expired_data(test_session, now=AHORA)

    assert resultado["outbox_messages"] == 2
    assert await _cuantos(test_session, OutboxMessage) == 3
