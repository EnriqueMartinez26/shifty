"""La plata que entra por un link reemplazado nunca queda en silencio.

Revision de perf/f4-pay (2026-09-25, #2). Un ``approved`` de un link viejo
(regenerado, re-tarifado) no se aplica al cobro vigente: aplicarlo dejaria el
link nuevo vivo y el cliente podria pagar dos veces. Pero la plata SI entro en
la cuenta de Mercado Pago de la tienda, y antes eso solo dejaba un numero en
``failed_webhooks``.

Ahora, cuando la integridad lo rechaza por ser de un link reemplazado:
- log de warning con los ids de tienda, cobro y pago de MP (sin datos
  personales);
- un evento a Sentry;
- un aviso al dueno ("Se recibio un pago sobre un link reemplazado") una sola
  vez por pago de MP, aunque MP reentregue el webhook.

Y los webhooks que agotan sus reintentos (dead letters) se ven en
``/ops/slo`` (``dead_letter_webhooks_24h``): antes dejaban de contar en cuanto
``processed_at`` se ponia al agotar los 10 intentos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

import modules.notifications.tasks as tasks
import modules.payments.processing as processing
from modules.notifications.model import Notification
from modules.stores.model import Store
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import (
    WEBHOOK_INBOX_MAX_ATTEMPTS,
    OutboxMessage,
    PaymentStatus,
    WebhookInbox,
)
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _cobro
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_link_regenerado_referencia_propia import (
    _aplicar,
    _pago_de_mp,
    _regenerado,
)
from tests.integration.test_mails_al_cliente import Buzon

EVENTO = "payment.received_on_replaced_link"


async def _avisos(session: AsyncSession) -> list[OutboxMessage]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(OutboxMessage).where(OutboxMessage.event_type == EVENTO)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_un_approved_de_un_link_reemplazado_avisa_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    reportes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        processing,
        "report_exception",
        lambda exc, **contexto: reportes.append(contexto),
    )
    turno, mp, vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "reemplazado-avisa"
    )
    cobro = await _cobro(test_session, turno)
    cobro_id, store_id = cobro.id, cobro.store_id
    payload = _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-viejo-9")

    with capture_logs() as logs:
        primero = await _aplicar(test_session, cobro, payload)
        # MP reentrega el mismo pago: no se avisa dos veces.
        segundo = await _aplicar(
            test_session, await _cobro(test_session, turno), payload
        )

    assert (primero, segundo) == (False, False)
    assert (await _cobro(test_session, turno)).status == PaymentStatus.PENDING.value
    avisos = await _avisos(test_session)
    assert len(avisos) == 1, avisos
    assert avisos[0].store_id == store_id
    assert avisos[0].payload["mp_payment_id"] == "mp-viejo-9"
    assert avisos[0].payload["payment_id"] == cobro_id
    advertencias = [
        e
        for e in logs
        if e["event"] == "payment_on_replaced_link" and e["log_level"] == "warning"
    ]
    assert len(advertencias) == 2, logs
    assert advertencias[0]["store_id"] == store_id
    assert advertencias[0]["payment_id"] == cobro_id
    assert advertencias[0]["mp_payment_id"] == "mp-viejo-9"
    # Sin datos personales en el log.
    assert not {"client_name", "email", "phone", "payer"} & set(advertencias[0])
    assert len(reportes) == 2 and reportes[0]["mp_payment_id"] == "mp-viejo-9"

    monkeypatch.setattr(tasks, "_send_email", Buzon())
    await process_outbox_batch(test_session)
    test_session.expire_all()
    notas = (
        (
            await test_session.execute(
                select(Notification).where(Notification.type == EVENTO)
            )
        )
        .scalars()
        .all()
    )
    assert len(notas) == 1
    assert "link reemplazado" in notas[0].title.lower()
    assert "mercado pago" in (notas[0].body or "").lower()


@pytest.mark.asyncio
async def test_un_in_process_de_un_link_reemplazado_no_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin plata acreditada no hay nada que revisar: solo no se aplica."""
    turno, mp, vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "reemplazado-en-proceso"
    )
    cobro = await _cobro(test_session, turno)
    payload = _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-x")
    payload["status"] = payload["data"]["status"] = "in_process"

    assert await _aplicar(test_session, cobro, payload) is False
    assert await _avisos(test_session) == []


@pytest.mark.asyncio
async def test_los_dead_letters_del_inbox_se_ven_en_el_slo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, token = await register_and_login(
        client, slug="slo-dead-letter", email="slo-dead-letter@example.com"
    )
    ahora = datetime.now(timezone.utc)
    tienda = (
        await test_session.execute(select(Store.id).where(Store.public_id == store))
    ).scalar_one()
    for n, (procesado, intentos) in enumerate(
        (
            (ahora - timedelta(hours=1), WEBHOOK_INBOX_MAX_ATTEMPTS),  # dead letter
            (ahora - timedelta(hours=30), WEBHOOK_INBOX_MAX_ATTEMPTS),  # viejo
            (ahora - timedelta(hours=1), 1),  # aplicado bien
        )
    ):
        test_session.add(
            WebhookInbox(
                store_id=tienda,
                event_id=f"mercadopago:slo-dead-{n}",
                payload={},
                processed_at=procesado,
                attempts=intentos,
                error="fallo" if intentos == WEBHOOK_INBOX_MAX_ATTEMPTS else None,
            )
        )
    await test_session.commit()

    res = await client.get("/ops/slo", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["metrics"]["dead_letter_webhooks_24h"] == 1
    assert "dead_letter_webhooks_24h" in cuerpo["thresholds"]
    assert "dead_letter_webhooks" in {a["code"] for a in cuerpo["alerts"]}
