"""El soft time limit de Celery corta el lote: no es un fallo del item.

Revision independiente de perf/f2b (2026-09-24). ``SoftTimeLimitExceeded``
es una ``Exception`` y los ``except Exception`` por item lo trataban como un
fallo mas: el inbox le gastaba un ``attempts`` al webhook (regla 7), la
conciliacion lo contaba como cobro fallido y el lote seguia hasta el hard
limit, que mata el proceso sin correr ningun ``finally``. Ahora el corte
aborta el job (se propaga), sin tocar ``attempts``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.jobs as jobs
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    WebhookInbox,
)


async def _corte(*_args: Any, **_kwargs: Any) -> Any:
    raise SoftTimeLimitExceeded()


async def _intentos(session: AsyncSession, modelo: Any) -> list[int]:
    await session.rollback()
    return list((await session.execute(select(modelo.attempts))).scalars().all())


@pytest.mark.asyncio
async def test_el_corte_en_un_webhook_aborta_el_inbox_sin_gastar_intentos(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_session.add(
        WebhookInbox(
            store_id="t-corte",
            provider="mercadopago",
            event_id="corte-1",
            payload={},
        )
    )
    await test_session.commit()

    async def enriquecer(_db: Any, *, payload: Any, **_: Any) -> Any:
        return payload

    monkeypatch.setattr(jobs, "enrich_mercadopago_webhook_payload", enriquecer)
    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", _corte)

    with pytest.raises(SoftTimeLimitExceeded):
        await jobs.process_webhook_inbox_batch(test_session)

    assert await _intentos(test_session, WebhookInbox) == [0]


@pytest.mark.asyncio
async def test_el_corte_en_un_mensaje_aborta_el_outbox_sin_gastar_intentos(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_session.add(OutboxMessage(store_id="t-corte", event_type="x", payload={}))
    await test_session.commit()
    monkeypatch.setattr(jobs, "_plan_outbox_message", _corte)

    with pytest.raises(SoftTimeLimitExceeded):
        await jobs.process_outbox_batch(test_session)

    assert await _intentos(test_session, OutboxMessage) == [0]


@pytest.mark.asyncio
async def test_registrar_fallo_no_anota_un_corte(test_session: AsyncSession) -> None:
    fila = WebhookInbox(store_id="t-corte", event_id="corte-2", payload={})
    test_session.add(fila)
    await test_session.commit()

    with pytest.raises(SoftTimeLimitExceeded):
        await jobs._registrar_fallo(test_session, fila, SoftTimeLimitExceeded())

    assert await _intentos(test_session, WebhookInbox) == [0]


async def _cobro_viejo(session: AsyncSession) -> None:
    session.add(
        PaymentGatewayConfig(
            store_id="t-corte", provider="mercadopago", encrypted_access_token="x"
        )
    )
    session.add(
        Payment(
            store_id="t-corte",
            appointment_id="t-corte-turno",
            provider="mercadopago",
            amount=Decimal("1000"),
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_el_corte_consultando_a_mp_aborta_la_conciliacion(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _cobro_viejo(test_session)
    monkeypatch.setattr(jobs, "_fetch_remote_payment", _corte)

    with pytest.raises(SoftTimeLimitExceeded):
        await jobs.reconcile_pending_payments(test_session)


@pytest.mark.asyncio
async def test_el_corte_aplicando_aborta_la_conciliacion(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _cobro_viejo(test_session)

    async def remoto(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"id": "mp-corte", "status": "approved"}

    async def libre(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(jobs, "_fetch_remote_payment", remoto)
    monkeypatch.setattr(jobs, "_lock_appointment_or_skip", libre)
    monkeypatch.setattr(jobs, "apply_mercadopago_webhook_payload", _corte)

    with pytest.raises(SoftTimeLimitExceeded):
        await jobs.reconcile_pending_payments(test_session)


@pytest.mark.asyncio
async def test_el_corte_venciendo_un_link_aborta_el_paso(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def sin_config(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(jobs, "load_gateway_configs", sin_config)
    monkeypatch.setattr(jobs, "expire_mercadopago_preference", _corte)
    reclamo = jobs._PreferenceExpireClaim(
        message_id="m",
        store_id="t-corte",
        preference_id="p",
        claimed_at=datetime.now(timezone.utc),
    )

    with pytest.raises(SoftTimeLimitExceeded):
        await jobs._expire_claimed_preferences(test_session, [reclamo])
