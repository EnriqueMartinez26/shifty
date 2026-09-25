"""Un cobro acreditado nunca se re-tarifa ni retira su link.

Revision de 7abb9b4..e5579b6 (2026-09-25, #5). Sintoma: pedir el link del
panel despues de un cambio de precio, o confirmar a mano con un importe, sobre
un turno ya PAGADO re-tarifaba el cobro acreditado y retiraba su link: nuevo
``link_ref``, ``external_payment_id`` borrado, importe pisado. Un reembolso o
contracargo posterior de MP llegaba con la referencia del link pagado, ya no
era la vigente, se clasificaba como "link reemplazado" y
``_notify_payment_reversed`` nunca avisaba al dueno.

Ahora un cobro ``approved``/``manual_confirmed`` conserva importe,
``link_ref`` y ``external_payment_id``. Decision del dueno (revision de
e5579b6..3b977a9, #5): pedir el link del panel responde 409
``PAYMENT_ALREADY_ACCREDITED`` (no hay nada que cobrar), con o sin cambio de
precio; confirmar a mano es un no-op 200 que devuelve el cobro tal como se
acredito (sin re-tarifar aunque el pedido traiga importe).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage, PaymentStatus
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _tienda,
    _Tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado


async def _pagado(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> tuple[_Tienda, str, tuple[Any, ...]]:
    """Turno con link del panel pagado por MP."""
    t = await _tienda(client, monkeypatch, slug, sena=False)
    turno = await _confirmado(client, t, 13)
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert link.status_code == 200, link.text
    cobro = await _cobro(session, turno)
    aplicado = await apply_mercadopago_webhook_payload(
        session,
        store_id=cobro.store_id,
        payload={
            "status": "approved",
            "data": {
                "id": "mp-pagado-1",
                "status": "approved",
                "external_reference": cobro.current_external_reference,
                "transaction_amount": float(cobro.amount),
                "currency_id": "ARS",
            },
        },
    )
    await session.commit()
    assert aplicado is True
    cobro = await _cobro(session, turno)
    assert cobro.status == PaymentStatus.APPROVED.value
    return t, turno, _foto(cobro)


def _foto(cobro: Any) -> tuple[Any, ...]:
    return (
        cobro.status,
        cobro.amount,
        cobro.link_ref,
        cobro.preference_id,
        cobro.external_payment_id,
    )


@pytest.mark.asyncio
async def test_el_link_del_panel_tras_un_cambio_de_precio_no_toca_un_cobro_pagado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, antes = await _pagado(client, test_session, monkeypatch, "acred-precio")
    precio = await client.patch(
        f"/services/{t.service}", headers=auth_headers(t.admin), json={"price": 15000}
    )
    assert precio.status_code == 200, precio.text

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "PAYMENT_ALREADY_ACCREDITED"
    assert _foto(await _cobro(test_session, turno)) == antes


@pytest.mark.asyncio
async def test_el_link_del_panel_sobre_un_cobro_pagado_es_409_sin_cambio_de_precio(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, antes = await _pagado(client, test_session, monkeypatch, "acred-link")

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "PAYMENT_ALREADY_ACCREDITED"
    assert _foto(await _cobro(test_session, turno)) == antes


@pytest.mark.asyncio
@pytest.mark.parametrize("importe", [None, "12345.00"])
async def test_confirmar_a_mano_un_cobro_pagado_es_un_no_op(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    importe: str | None,
) -> None:
    t, turno, antes = await _pagado(
        client, test_session, monkeypatch, f"acred-manual-{importe or 'sin'}"
    )
    eventos_antes = await _cantidad_de_eventos(test_session)

    res = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(t.admin),
        json={} if importe is None else {"amount": importe},
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["status"] == PaymentStatus.APPROVED.value, cuerpo
    assert Decimal(str(cuerpo["amount"])) == antes[1]
    assert _foto(await _cobro(test_session, turno)) == antes
    # Nada que vencer ni avisar: no se publico ningun evento.
    assert await _cantidad_de_eventos(test_session) == eventos_antes


async def _cantidad_de_eventos(session: AsyncSession) -> int:
    session.expire_all()
    return len((await session.execute(select(OutboxMessage.id))).all())


@pytest.mark.asyncio
async def test_un_reembolso_posterior_sigue_avisando_al_dueno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, _antes = await _pagado(
        client, test_session, monkeypatch, "acred-reembolso"
    )
    await client.patch(
        f"/services/{t.service}", headers=auth_headers(t.admin), json={"price": 15000}
    )
    await client.post(f"/payments/preferences/{turno}", headers=auth_headers(t.admin))
    cobro = await _cobro(test_session, turno)

    aplicado = await apply_mercadopago_webhook_payload(
        test_session,
        store_id=cobro.store_id,
        payload={
            "status": "refunded",
            "data": {
                "id": "mp-pagado-1",
                "status": "refunded",
                "external_reference": cobro.current_external_reference,
                "transaction_amount": float(Decimal("10000")),
                "currency_id": "ARS",
            },
        },
    )
    await test_session.commit()

    assert aplicado is True
    cobro = await _cobro(test_session, turno)
    cobro_id = cobro.id
    assert cobro.status == PaymentStatus.REFUNDED.value
    test_session.expire_all()
    avisos = [
        m.event_type
        for m in (await test_session.execute(select(OutboxMessage))).scalars()
        if m.payload.get("payment_id") == cobro_id
    ]
    assert NotificationType.PAYMENT_REFUNDED.value in avisos
