"""Inbox y conciliacion: fase A con presupuesto de tiempo y lote de 25.

F1-20 (plan de rendimiento, R9-08 y R3-06, 2026-09-24). Los dos lotes le
preguntan a Mercado Pago en la fase A (sin lock) y aplican en la fase B. La
fase A no tenia tope: 100 filas x hasta 20 s por consulta. Con MP lento el
hard time limit de Celery (150 s) mataba la tarea ANTES de la fase B, asi que
no se aplicaba nada y la corrida siguiente volvia a tomar las mismas 100
filas: ningun webhook reintentado se aplicaba nunca.

Ahora la fase A corta a los 60 s (lo que falta queda para la corrida
siguiente, sin gastarle un intento), el lote es de 25 y la fase B aplica
siempre lo que la fase A alcanzo a consultar. La conciliacion ademas ignora
los cobros de menos de ``RECONCILIATION_MIN_AGE_MINUTES``: el cliente
todavia esta en el checkout y preguntarle a MP es gastar la corrida.

El reloj es falso: cada consulta a MP "tarda" 3 s sin dormir de verdad.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.jobs as jobs
from core.config import settings
from modules.payments.model import (
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
    WebhookInbox,
)

PENDIENTES = 60
DEMORA_DE_MP = 3.0


class _Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0
        self.inicio = self.ahora

    def __call__(self) -> float:
        return self.ahora

    @property
    def transcurrido(self) -> float:
        return self.ahora - self.inicio


@pytest.fixture
def reloj(monkeypatch: pytest.MonkeyPatch) -> _Reloj:
    falso = _Reloj()
    monkeypatch.setattr(jobs, "_reloj", falso)
    return falso


@pytest.mark.asyncio
async def test_el_inbox_aplica_lo_que_entra_en_el_presupuesto_y_sigue_despues(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, reloj: _Reloj
) -> None:
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(PENDIENTES):
        test_session.add(
            WebhookInbox(
                store_id="tienda-f120",
                provider="mercadopago",
                event_id=f"f120-{i:03d}",
                event_type="payment",
                payload={"data": {"id": str(i)}},
                created_at=base + timedelta(seconds=i),
            )
        )
    await test_session.commit()

    consultados: list[str] = []

    async def mp_lento(db: Any, *, payload: dict[str, Any], **_: Any) -> Any:
        reloj.ahora += DEMORA_DE_MP
        consultados.append(str(payload["data"]["id"]))
        return {**payload, "status": "approved"}

    async def aplicar(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(jobs, "enrich_mercadopago_webhook_payload", mp_lento)
    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", aplicar)

    primera = await jobs.process_webhook_inbox_batch(test_session)

    # 60 s / 3 s = 20 consultas; la que empieza con el presupuesto agotado no.
    assert primera["processed"] == 20, primera
    assert primera["inspected"] == 20, primera
    assert reloj.transcurrido <= 60 + DEMORA_DE_MP
    assert reloj.transcurrido < settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS
    # Lo que no se consulto no gasto un intento: queda intacto para despues.
    intactos = (
        (
            await test_session.execute(
                select(WebhookInbox).where(WebhookInbox.processed_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    assert len(intactos) == PENDIENTES - 20
    assert all(fila.attempts == 0 for fila in intactos)

    reloj.inicio = reloj.ahora
    segunda = await jobs.process_webhook_inbox_batch(test_session)
    assert segunda["processed"] == 20, segunda
    # La segunda corrida avanza: no repite los ya aplicados.
    assert len(set(consultados)) == 40


@pytest.mark.asyncio
async def test_el_lote_por_defecto_es_de_25(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, reloj: _Reloj
) -> None:
    for i in range(30):
        test_session.add(
            WebhookInbox(
                store_id="tienda-f120-25",
                provider="mercadopago",
                event_id=f"f120-25-{i:03d}",
                payload={"data": {"id": str(i)}},
            )
        )
    await test_session.commit()

    async def mp_rapido(db: Any, *, payload: dict[str, Any], **_: Any) -> Any:
        return payload

    async def aplicar(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(jobs, "enrich_mercadopago_webhook_payload", mp_rapido)
    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", aplicar)

    resultado = await jobs.process_webhook_inbox_batch(test_session)
    assert resultado["processed"] == 25, resultado


async def _cobros_pendientes(
    session: AsyncSession, *, store_id: str, cuantos: int, creados: datetime
) -> list[str]:
    ids: list[str] = []
    for i in range(cuantos):
        cobro = Payment(
            store_id=store_id,
            appointment_id=f"{store_id}-turno-{creados.timestamp():.0f}-{i:03d}",
            provider="mercadopago",
            amount=Decimal("1000"),
            created_at=creados + timedelta(seconds=i),
        )
        session.add(cobro)
        await session.flush()
        ids.append(cobro.id)
    return ids


@pytest.mark.asyncio
async def test_la_conciliacion_tiene_presupuesto_y_edad_minima(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, reloj: _Reloj
) -> None:
    tienda = "tienda-f120-concilia"
    test_session.add(
        PaymentGatewayConfig(
            store_id=tienda, provider="mercadopago", encrypted_access_token="x"
        )
    )
    ahora = datetime.now(timezone.utc)
    viejos = await _cobros_pendientes(
        test_session,
        store_id=tienda,
        cuantos=PENDIENTES,
        creados=ahora - timedelta(hours=2),
    )
    recien_creados = await _cobros_pendientes(
        test_session,
        store_id=tienda,
        cuantos=5,
        # Mas viejos que ``now - edad minima`` no: el cliente sigue pagando.
        creados=ahora
        - timedelta(minutes=settings.RECONCILIATION_MIN_AGE_MINUTES)
        + timedelta(minutes=1),
    )
    await test_session.commit()

    consultados: list[str] = []

    async def mp_lento(
        db: Any, payment: Payment, *_args: Any, **_kwargs: Any
    ) -> dict[str, Any]:
        reloj.ahora += DEMORA_DE_MP
        consultados.append(payment.id)
        return {"id": f"mp-{payment.id}", "status": "approved"}

    async def aplicar(db: Any, *, payload: dict[str, Any], **_kwargs: Any) -> bool:
        # Un cambio de estado real: ``reconciled`` no cuenta los no-ops
        # (revision de e5579b6..3b977a9, #4 f).
        pago = await db.get(Payment, str(payload["data"]["id"]).removeprefix("mp-"))
        assert pago is not None
        return bool(pago.apply_status(PaymentStatus.APPROVED.value))

    async def turno_libre(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(jobs, "_fetch_remote_payment", mp_lento)
    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", aplicar)
    monkeypatch.setattr(jobs, "_lock_appointment_or_skip", turno_libre)

    resultado = await jobs.reconcile_pending_payments(test_session)

    assert settings.RECONCILIATION_MIN_AGE_MINUTES == 10
    assert resultado["reconciled"] == 20, resultado
    assert reloj.transcurrido <= 60 + DEMORA_DE_MP
    assert set(consultados) <= set(viejos)
    assert not set(consultados) & set(recien_creados)
