"""Una reversa de OTRO pago de MP sobre un cobro asentado no queda en silencio.

Re-revision de la PR #112 (hallazgo 1, WARNING). Un cobro asentado solo acepta
eventos del pago de MP que lo acredito, y un ``manual_confirmed`` ninguno
(``processing._es_de_otro_pago``). El ``approved`` de otro pago ya avisaba
"pago duplicado"; cualquier otro estado solo dejaba un log de info. Caso real:
el cliente paga por el link de MP y manda el comprobante por WhatsApp, el dueno
lo registra a mano antes de que llegue el webhook y el pago de MP es el UNICO
real. Si despues el cliente lo desconoce (contracargo) o abre una disputa,
Shifty callaba y la sena seguia contando como ingreso.

Ahora el evento sigue sin aplicarse, pero un contracargo, una disputa o una
devolucion de ese otro pago avisan al dueno una vez por (pago de MP, estado
remoto). Excepciones: un ``rejected`` (no se movio plata) y un ``refunded``
de un pago por el que ya se publico el aviso de duplicado (el dueno hizo lo
que se le pidio).

Hallazgo 2 (SUGERENCIA): un cobro devuelto sin id de MP (una sena manual
reembolsada desde el panel) se tragaba en silencio un ``approved`` posterior.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.processing as processing
from modules.notifications.model import Notification, NotificationType
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage, PaymentStatus, WebhookInbox
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_sena_por_mp_o_whatsapp import SENA, _cobro, _eventos
from tests.integration.test_sena_por_whatsapp_regla_3 import (
    _mp_con_pago,
    _remoto,
    _sena_registrada_a_mano_con_link,
    _webhook,
)

EVENTO = "payment.reversal_of_other_payment"


def _sentry(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    reportes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        processing,
        "report_exception",
        lambda exc, **contexto: reportes.append(contexto),
    )
    return reportes


async def _avisos_de_duplicado(session: AsyncSession) -> list[OutboxMessage]:
    return await _eventos(session, NotificationType.PAYMENT_ON_REPLACED_LINK.value)


async def _inbox_cerrado(session: AsyncSession) -> None:
    inbox = (await session.execute(select(WebhookInbox))).scalars().all()
    assert inbox, "el webhook no paso por el inbox"
    assert all(e.processed_at is not None and e.attempts == 0 for e in inbox), [
        (e.attempts, e.error) for e in inbox
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("estado", "titulo", "que"),
    [
        ("charged_back", "Contracargo en Mercado Pago", "un contracargo"),
        ("in_mediation", "Disputa abierta en Mercado Pago", "una disputa"),
    ],
)
async def test_una_reversa_de_mp_sobre_una_sena_registrada_a_mano_avisa_una_vez(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
    titulo: str,
    que: str,
) -> None:
    """El pago de MP es el unico real (el ``approved`` nunca llego o llego
    despues del registro a mano): su contracargo o su disputa avisan, una vez
    aunque MP reentregue el evento, y no tocan el cobro."""
    reportes = _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, f"reversa-{estado}"
    )
    _mp_con_pago(monkeypatch, _remoto(turno, cobro, "mp-unico", estado, importe))

    await _webhook(client, t.store, f"evt-{estado}-1", "mp-unico")
    await _webhook(client, t.store, f"evt-{estado}-2", "mp-unico")

    final = await _cobro(test_session, turno)
    assert final is not None
    assert (final.status, final.external_payment_id, final.amount) == (
        PaymentStatus.MANUAL_CONFIRMED.value,
        None,
        SENA,
    )
    cobro_id = final.id
    avisos = await _eventos(test_session, EVENTO)
    assert len(avisos) == 1, [a.payload for a in avisos]
    assert avisos[0].payload["aviso"] == f"reverso:mp-unico:{estado}"
    assert avisos[0].payload["remote_status"] == estado
    assert avisos[0].payload["mp_payment_id"] == "mp-unico"
    assert avisos[0].payload["payment_id"] == cobro_id
    assert await _avisos_de_duplicado(test_session) == []
    assert len(reportes) == 1 and reportes[0]["mp_payment_id"] == "mp-unico"
    await _inbox_cerrado(test_session)

    await process_outbox_batch(test_session)
    nota = (
        await test_session.execute(
            select(Notification).where(Notification.type == EVENTO)
        )
    ).scalar_one()
    assert nota.title == titulo
    cuerpo = nota.body or ""
    assert f"Mercado Pago informó {que} del pago mp-unico" in cuerpo
    assert "ya estaba registrada" in cuerpo
    assert "no se modificó el cobro" in cuerpo
    assert nota.appointment_id == turno


@pytest.mark.asyncio
async def test_el_contracargo_de_un_duplicado_ya_avisado_igual_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El aviso de duplicado pide DEVOLVER el pago; un contracargo no es lo
    que el dueno hizo: si ademas lo devolvio, la tienda pierde dos veces."""
    _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, "reversa-dup-contracargo"
    )
    for estado in ("approved", "charged_back"):
        _mp_con_pago(monkeypatch, _remoto(turno, cobro, "mp-dup", estado, importe))
        await _webhook(client, t.store, f"evt-dup-{estado}", "mp-dup")

    assert len(await _avisos_de_duplicado(test_session)) == 1
    avisos = await _eventos(test_session, EVENTO)
    assert [a.payload["aviso"] for a in avisos] == ["reverso:mp-dup:charged_back"]


@pytest.mark.asyncio
async def test_devolver_el_duplicado_ya_avisado_no_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El dueno siguio el aviso de duplicado y devolvio ese pago en MP: su
    ``refunded`` es lo que se le pidio, no una novedad."""
    reportes = _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, "reversa-dup-devuelto"
    )
    for estado in ("approved", "refunded"):
        _mp_con_pago(monkeypatch, _remoto(turno, cobro, "mp-dup", estado, importe))
        await _webhook(client, t.store, f"evt-dup-{estado}", "mp-dup")

    assert len(await _avisos_de_duplicado(test_session)) == 1
    assert await _eventos(test_session, EVENTO) == []
    # Solo el reporte del duplicado.
    assert len(reportes) == 1
    final = await _cobro(test_session, turno)
    assert final is not None and final.status == PaymentStatus.MANUAL_CONFIRMED.value
    await _inbox_cerrado(test_session)


@pytest.mark.asyncio
async def test_la_devolucion_de_un_pago_nunca_avisado_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin aviso de duplicado previo (el ``approved`` se perdio), la devolucion
    del unico pago real de MP es plata que se fue: avisa."""
    _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, "reversa-devuelto-sin-aviso"
    )
    _mp_con_pago(monkeypatch, _remoto(turno, cobro, "mp-solo", "refunded", importe))

    await _webhook(client, t.store, "evt-solo-refunded", "mp-solo")

    avisos = await _eventos(test_session, EVENTO)
    assert [a.payload["aviso"] for a in avisos] == ["reverso:mp-solo:refunded"]
    await process_outbox_batch(test_session)
    nota = (
        await test_session.execute(
            select(Notification).where(Notification.type == EVENTO)
        )
    ).scalar_one()
    assert "una devolución del pago mp-solo" in (nota.body or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["rejected", "in_process"])
async def test_un_evento_sin_plata_movida_de_otro_pago_no_avisa(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    reportes = _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, f"reversa-sin-plata-{estado}"
    )
    _mp_con_pago(monkeypatch, _remoto(turno, cobro, "mp-nada", estado, importe))

    await _webhook(client, t.store, f"evt-nada-{estado}", "mp-nada")

    assert await _eventos(test_session, EVENTO) == []
    assert reportes == []
    await _inbox_cerrado(test_session)


@pytest.mark.asyncio
async def test_una_reversa_de_otro_pago_que_no_es_de_este_cobro_no_avisa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hallazgo 4: la identidad corre ANTES que la guarda del otro pago. Un
    contracargo en otra moneda no es de este cobro: se rechaza por integridad
    y no se le avisa al dueno de una plata que no es suya."""
    reportes = _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, "reversa-ajena"
    )
    remoto = _remoto(turno, cobro, "mp-ajeno", "charged_back", importe)
    remoto["currency_id"] = "USD"
    _mp_con_pago(monkeypatch, remoto)

    await _webhook(client, t.store, "evt-ajeno", "mp-ajeno")

    assert await _eventos(test_session, EVENTO) == []
    assert reportes == []
    evento = (await test_session.execute(select(WebhookInbox))).scalar_one()
    assert evento.processed_at is None and "moneda" in (evento.error or "")


# ---------------------------------------------------------------------------
# Hallazgo 2: cobro devuelto sin id de MP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_approved_sobre_una_sena_manual_ya_devuelta_avisa_duplicado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La sena registrada a mano se devolvio desde el panel (sin id de MP) y
    despues entra el pago del link: ``refunded -> approved`` es ilegal, asi
    que antes se descartaba sin rastro. Es plata que entro: aviso de
    duplicado, una vez por pago de MP, y el cobro sigue devuelto."""
    reportes = _sentry(monkeypatch)
    t, turno, cobro, importe = await _sena_registrada_a_mano_con_link(
        client, test_session, monkeypatch, "reversa-devuelta-sin-id"
    )
    devuelto = await client.post(
        f"/payments/{cobro.id}/refund",
        headers=auth_headers(t.token),
        json={"manual": True, "reason": "el cliente no pudo venir"},
    )
    assert devuelto.status_code == 200, devuelto.text
    releido = await _cobro(test_session, turno)
    assert releido is not None
    assert (releido.status, releido.external_payment_id) == (
        PaymentStatus.REFUNDED.value,
        None,
    )
    _mp_con_pago(monkeypatch, _remoto(turno, releido, "mp-tarde", "approved", importe))

    await _webhook(client, t.store, "evt-tarde-1", "mp-tarde")
    await _webhook(client, t.store, "evt-tarde-2", "mp-tarde")

    avisos = await _avisos_de_duplicado(test_session)
    assert len(avisos) == 1, [a.payload for a in avisos]
    assert avisos[0].payload["aviso"] == "pago:mp-tarde"
    assert avisos[0].payload["duplicado"] is True
    assert len(reportes) == 1
    final = await _cobro(test_session, turno)
    assert final is not None
    assert (final.status, final.external_payment_id) == (
        PaymentStatus.REFUNDED.value,
        None,
    )
    await _inbox_cerrado(test_session)
