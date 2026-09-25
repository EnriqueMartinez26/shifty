"""Regenerar desde el panel el link de un cobro vencido deja un cobro vivo.

Revision de perf/f4-pay (2026-09-25, #5, opcion b del coordinador). Antes:
``POST /payments/preferences/{id}`` sobre un turno vivo cuyo cobro estaba
``expired`` devolvia el link VIEJO (ya vencido en MP) y el cobro seguia
``expired``; y si el importe cambiaba, sellaba un link nuevo sobre un cobro
``expired``, que no es un cobro vivo: D1 y D2 no lo veian.

Ahora la regeneracion:
- fase 1 (turno lockeado): el cobro vencido pierde su link viejo (queda un
  placeholder, asi se pide uno nuevo) y el viejo se manda a vencer;
- fase 2 (turno lockeado otra vez, no soltado): sella un ``preference_id``
  NUEVO y reabre el cobro con ``Payment.reopen_for_panel_link``.

Un webhook tardio de la preferencia VIEJA:
- con el cobro ya regenerado, no pasa la integridad (preferencia distinta):
  no toca el cobro nuevo;
- con el cobro todavia vencido, ``in_process`` no lo reabre (el grafo general
  no tiene ``expired -> pending``) y ``approved`` registra la plata por el
  camino de siempre (``expired -> approved``, un solo aviso al dueno).
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _tienda,
    _Tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado


def _mp_con_preferencias_nuevas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    creadas: list[str] = []
    numero = itertools.count(1)

    async def mp(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST" and path == "/checkout/preferences", (method, path)
        preferencia = f"pref-regen-{next(numero)}"
        creadas.append(preferencia)
        return {
            "id": preferencia,
            "init_point": f"https://www.mercadopago.com/checkout?pref={preferencia}",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    return creadas


async def _con_cobro_vencido(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> tuple[_Tienda, str, list[str]]:
    t = await _tienda(client, monkeypatch, slug, sena=False)
    creadas = _mp_con_preferencias_nuevas(monkeypatch)
    turno = await _confirmado(client, t, 13)
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert link.status_code == 200, link.text
    cobro = await _cobro(session, turno)
    # Lo que deja MP al vencer el link (webhook ``expired``): el turno sigue vivo.
    assert cobro.apply_status(PaymentStatus.EXPIRED.value)
    await session.commit()
    return t, turno, creadas


async def _webhook_de(
    session: AsyncSession,
    cobro: Payment,
    *,
    preferencia: str,
    estado: str,
    externo: str,
) -> bool:
    return await apply_mercadopago_webhook_payload(
        session,
        store_id=cobro.store_id,
        payload={
            "status": estado,
            "data": {
                "id": externo,
                "status": estado,
                "external_reference": cobro.appointment_id,
                "preference_id": preferencia,
                "transaction_amount": float(cobro.amount),
                "currency_id": "ARS",
            },
        },
    )


@pytest.mark.asyncio
async def test_regenerar_sella_un_link_nuevo_y_reabre_el_cobro(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "regen-reabre"
    )
    (vieja,) = creadas

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 200, res.text
    cobro = await _cobro(test_session, turno)
    estado, preferencia = cobro.status, cobro.preference_id
    assert estado == PaymentStatus.PENDING.value
    assert preferencia == creadas[-1] != vieja
    # El link viejo se manda a vencer en MP.
    assert vieja in {
        e.payload["preference_id"] for e in await _vencimientos(test_session, turno)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["in_process", "approved"])
async def test_un_webhook_de_la_preferencia_vieja_no_toca_el_cobro_regenerado(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, f"regen-vieja-{estado}"
    )
    (vieja,) = creadas
    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert res.status_code == 200, res.text
    cobro = await _cobro(test_session, turno)
    nueva = cobro.preference_id

    # Es de un link reemplazado: no se aplica (y si es ``approved``, avisa;
    # tests/integration/test_pago_en_link_reemplazado_avisa.py).
    aplicado = await _webhook_de(
        test_session, cobro, preferencia=vieja, estado=estado, externo="mp-viejo"
    )
    await test_session.commit()
    assert aplicado is False

    cobro = await _cobro(test_session, turno)
    assert (cobro.status, cobro.preference_id) == (PaymentStatus.PENDING.value, nueva)


@pytest.mark.asyncio
async def test_in_process_tardio_no_reabre_un_cobro_vencido(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "regen-in-process"
    )
    cobro = await _cobro(test_session, turno)

    await _webhook_de(
        test_session,
        cobro,
        preferencia=creadas[0],
        estado="in_process",
        externo="mp-en-proceso",
    )
    await test_session.commit()

    assert (await _cobro(test_session, turno)).status == PaymentStatus.EXPIRED.value


@pytest.mark.asyncio
async def test_approved_tardio_de_un_cobro_vencido_registra_la_plata_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "regen-aprobado"
    )
    cobro = await _cobro(test_session, turno)
    cobro_id = cobro.id

    for _ in range(2):  # reentrega del mismo pago
        await _webhook_de(
            test_session,
            await _cobro(test_session, turno),
            preferencia=creadas[0],
            estado="approved",
            externo="mp-aprobado-tarde",
        )
        await test_session.commit()

    assert (await _cobro(test_session, turno)).status == PaymentStatus.APPROVED.value
    test_session.expire_all()
    avisos = [
        m
        for m in (await test_session.execute(select(OutboxMessage))).scalars()
        if m.payload.get("payment_id") == cobro_id
        and m.event_type
        in {
            NotificationType.PAYMENT_APPROVED.value,
            NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value,
        }
    ]
    assert len(avisos) == 1, [a.event_type for a in avisos]
