"""Cada evento de pago que se publica tiene consumidor (B2-17).

2026-09-19, hallazgo B2-17: tres eventos se publicaban en el outbox y nadie
los consumia -- ``_build_store_notification`` devolvia None y el lote los
marcaba procesados sin efecto --: ``payment.refunded``,
``payment.manual_confirmed`` y ``payment.preference.created``. La tabla
crecia con filas que solo inflaban ``outbox_stats``, y ``manual_confirm``
republicaba en cada doble clic.

Decision (sugerencia del brief, OK de Mateo): ``payment.refunded`` gana
consumidor -- aviso "Reembolso registrado" en el panel del dueno --; los
otros dos dejan de publicarse porque nadie los lee (verificado con git grep
en backend, front y tests).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
    _stub_preference,
)


async def _turno(client: AsyncClient, slug: str) -> tuple[str, str]:
    _store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return token, cast(str, reserva.json()["public_id"])


async def _tipos(session: AsyncSession) -> list[str]:
    return list(
        (await session.execute(select(OutboxMessage.event_type))).scalars().all()
    )


@pytest.mark.asyncio
async def test_link_de_pago_y_confirmacion_manual_no_publican_eventos_sin_consumidor(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_preference(monkeypatch)
    token, turno = await _turno(client, "b217-sin-consumidor")

    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert link.status_code == 200, link.text
    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(token), json={}
    )
    assert confirmado.status_code == 200, confirmado.text

    tipos = await _tipos(test_session)
    assert "payment.preference.created" not in tipos, tipos
    assert "payment.manual_confirmed" not in tipos, tipos


@pytest.mark.asyncio
async def test_el_reembolso_registrado_avisa_al_panel_del_dueno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    token, turno = await _turno(client, "b217-reembolso")
    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(token), json={}
    )
    assert confirmado.status_code == 200, confirmado.text
    cobro = confirmado.json()["public_id"]
    reembolso = await client.post(
        f"/payments/{cobro}/refund",
        headers=auth_headers(token),
        json={"manual": True, "reason": "devuelto en efectivo"},
    )
    assert reembolso.status_code == 200, reembolso.text

    await process_outbox_batch(test_session)

    avisos = list(
        (
            await test_session.execute(
                select(Notification).where(Notification.type == "payment.refunded")
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1, avisos
    assert avisos[0].title == "Reembolso registrado"
    assert avisos[0].appointment_id == turno
    assert confirmado.json()["amount"] in (avisos[0].body or "")
