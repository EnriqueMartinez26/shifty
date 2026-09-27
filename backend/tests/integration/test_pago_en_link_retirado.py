"""Un pago aprobado sobre un link RETIRADO del mismo cobro no se pierde.

Revision de 7abb9b4..e5579b6 (2026-09-25, #1, hueco de plata). Con
``binary_mode`` MP aprueba o rechaza en el momento, pero el aviso de un pago
del link L puede llegar despues de que L se retiro (regenerar un cobro
vencido, o re-tarifar): webhook tardio, reentregado o perdido, o un pago en L
antes de que MP lo venciera. Ese pago no se aplicaba: el
cobro seguia ``pending`` con el link nuevo vivo (el cliente podia pagar dos
veces) y la conciliacion no lo veia porque solo buscaba la referencia vigente.

Ahora cada link retirado queda en ``payment_link_history`` (referencia,
preferencia, importe y moneda de ESE link). Un ``approved`` con la referencia
de un link retirado del mismo cobro:
- cobro sin acreditar e importe/moneda de ESE link: se aplica por el camino
  normal (aviso normal al dueno) y el link vigente se vence en la misma
  transaccion; el cobro pasa a ser el del link pagado;
- cobro ya acreditado: pago duplicado, camino de alerta ("devolvelo desde
  Mercado Pago"), una vez por pago de MP;
- importe distinto: camino de alerta.
La conciliacion tambien busca en MP por las referencias de los links
retirados del cobro en los ultimos ``RETIRED_LINK_SEARCH_DAYS`` dias.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from core.config import settings
from modules.notifications.model import NotificationType
from modules.payments.jobs import reconcile_pending_payments
from modules.payments.links import (
    RETIRED_LINK_SEARCH_DAYS,
    retired_link_references,
)
from modules.payments.model import OutboxMessage, PaymentLinkHistory, PaymentStatus
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _cobro
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado
from tests.integration.test_link_regenerado_referencia_propia import (
    _MP,
    _aplicar,
    _pago_de_mp,
    _regenerado,
)
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _tienda


async def _eventos(session: AsyncSession, cobro_id: str) -> list[OutboxMessage]:
    session.expire_all()
    return [
        m
        for m in (await session.execute(select(OutboxMessage))).scalars()
        if m.payload.get("payment_id") == cobro_id
    ]


@pytest.mark.asyncio
async def test_retirar_un_link_lo_anota_en_el_historial(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "retirado-historial"
    )
    cobro = await _cobro(test_session, turno)

    filas = (
        (
            await test_session.execute(
                select(PaymentLinkHistory).where(
                    PaymentLinkHistory.payment_id == cobro.id
                )
            )
        )
        .scalars()
        .all()
    )

    assert [(f.preference_id, f.store_id) for f in filas] == [(vieja, cobro.store_id)]
    fila = filas[0]
    assert f"{turno}:{fila.link_ref}" == mp.referencias[vieja]
    assert fila.amount == cobro.amount and fila.currency == "ARS"


@pytest.mark.asyncio
async def test_un_approved_de_un_link_retirado_se_aplica_y_vence_el_vigente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, nueva = await _regenerado(
        client, test_session, monkeypatch, "retirado-aplica"
    )
    cobro = await _cobro(test_session, turno)
    cobro_id = cobro.id

    aplicado = await _aplicar(
        test_session,
        cobro,
        _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-cupon-1"),
    )

    assert aplicado is True
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.APPROVED.value
    # El cobro queda con el link que se pago; el vigente se vencio.
    assert cobro.preference_id == vieja
    assert cobro.current_external_reference == mp.referencias[vieja]
    assert cobro.external_payment_id == "mp-cupon-1"
    eventos = await _eventos(test_session, cobro_id)
    vencidas = [
        e.payload["preference_id"]
        for e in eventos
        if e.event_type == EVENT_PREFERENCE_EXPIRE
    ]
    assert nueva in vencidas
    aprobados = [
        e for e in eventos if e.event_type == NotificationType.PAYMENT_APPROVED.value
    ]
    assert len(aprobados) == 1
    assert not [
        e for e in eventos if e.event_type == "payment.received_on_replaced_link"
    ]


@pytest.mark.asyncio
async def test_un_approved_de_un_link_retirado_con_el_cobro_pago_es_duplicado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, nueva = await _regenerado(
        client, test_session, monkeypatch, "retirado-duplicado"
    )
    cobro = await _cobro(test_session, turno)
    cobro_id = cobro.id
    assert await _aplicar(
        test_session,
        cobro,
        _pago_de_mp(cobro, referencia=mp.referencias[nueva], externo="mp-nuevo-1"),
    )

    aplicado = await _aplicar(
        test_session,
        await _cobro(test_session, turno),
        _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-viejo-1"),
    )

    assert aplicado is False
    cobro = await _cobro(test_session, turno)
    assert (cobro.status, cobro.preference_id, cobro.external_payment_id) == (
        PaymentStatus.APPROVED.value,
        nueva,
        "mp-nuevo-1",
    )
    alertas = [
        e
        for e in await _eventos(test_session, cobro_id)
        if e.event_type == "payment.received_on_replaced_link"
    ]
    assert len(alertas) == 1
    assert alertas[0].payload["duplicado"] is True
    assert alertas[0].payload["mp_payment_id"] == "mp-viejo-1"


@pytest.mark.asyncio
async def test_un_approved_de_un_link_retirado_con_otro_importe_alerta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    turno, mp, vieja, nueva = await _regenerado(
        client, test_session, monkeypatch, "retirado-importe"
    )
    cobro = await _cobro(test_session, turno)
    cobro_id = cobro.id
    payload = _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-raro")
    payload["data"]["transaction_amount"] = 1.0

    aplicado = await _aplicar(test_session, cobro, payload)

    assert aplicado is False
    cobro = await _cobro(test_session, turno)
    assert (cobro.status, cobro.preference_id) == (PaymentStatus.PENDING.value, nueva)
    alertas = [
        e
        for e in await _eventos(test_session, cobro_id)
        if e.event_type == "payment.received_on_replaced_link"
    ]
    assert len(alertas) == 1 and alertas[0].payload["duplicado"] is False


@pytest.mark.asyncio
async def test_retirar_por_re_tarifa_y_pagar_el_link_viejo_con_su_importe(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El retiro por re-tarifa (``_needs_provider_link``) tambien se anota, con
    el importe del link retirado: el pago del link viejo por ese importe se
    aplica y el cobro queda por la plata que entro."""
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    t = await _tienda(client, monkeypatch, "retirado-retarifa", sena=False)
    mp = _MP()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    turno = await _confirmado(client, t, 13)
    primero = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert primero.status_code == 200, primero.text
    viejo = await _cobro(test_session, turno)
    vieja, importe_viejo = str(viejo.preference_id), viejo.amount
    precio = await client.patch(
        f"/services/{t.service}", headers=auth_headers(t.admin), json={"price": 15000}
    )
    assert precio.status_code == 200, precio.text
    segundo = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert segundo.status_code == 200, segundo.text
    cobro = await _cobro(test_session, turno)
    assert cobro.amount != importe_viejo and cobro.preference_id != vieja

    payload = _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-viejo-2")
    payload["data"]["transaction_amount"] = float(importe_viejo)
    aplicado = await _aplicar(test_session, cobro, payload)

    assert aplicado is True
    cobro = await _cobro(test_session, turno)
    assert (cobro.status, cobro.amount, cobro.preference_id) == (
        PaymentStatus.APPROVED.value,
        importe_viejo,
        vieja,
    )


@pytest.mark.asyncio
async def test_la_conciliacion_encuentra_un_pago_de_un_link_retirado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    turno, mp, vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "retirado-concilia"
    )
    cobro = await _cobro(test_session, turno)
    referencia_vieja = mp.referencias[vieja]
    remoto: dict[str, Any] = _pago_de_mp(
        cobro, referencia=referencia_vieja, externo="mp-cupon-9"
    )["data"]
    busquedas: list[str] = []

    async def mp_busqueda(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        busquedas.append(path)
        if path.startswith("/v1/payments/search"):
            if referencia_vieja.replace(":", "%3A") in path:
                return {"results": [remoto]}
            return {"results": []}
        return remoto

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_busqueda)

    resultado = await reconcile_pending_payments(test_session)

    assert resultado["reconciled"] == 1, (resultado, busquedas)
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.APPROVED.value
    assert cobro.preference_id == vieja


@pytest.mark.asyncio
async def test_la_conciliacion_busca_links_retirados_de_la_ultima_semana(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ventana de ``RETIRED_LINK_SEARCH_DAYS`` = 7 (seguimiento de la revision
    de 7abb9b4..e5579b6). Las preferencias usan ``binary_mode``: MP aprueba o
    rechaza en el momento, sin cupones de efectivo pendientes. Lo que la
    ventana cubre son webhooks tardios o perdidos y reentregas; una semana
    alcanza y acota la busqueda en MP de cada corrida."""
    turno, mp, vieja, _nueva = await _regenerado(
        client, test_session, monkeypatch, "retirado-ventana"
    )
    cobro = await _cobro(test_session, turno)
    retirado = (
        await test_session.execute(
            select(PaymentLinkHistory.retired_at).where(
                PaymentLinkHistory.payment_id == cobro.id
            )
        )
    ).scalar_one()

    adentro = await retired_link_references(
        test_session, [cobro], ahora=retirado + timedelta(days=6, hours=23)
    )
    afuera = await retired_link_references(
        test_session, [cobro], ahora=retirado + timedelta(days=7, minutes=1)
    )

    assert RETIRED_LINK_SEARCH_DAYS == 7
    assert adentro == {cobro.id: [mp.referencias[vieja]]}
    assert afuera == {}
