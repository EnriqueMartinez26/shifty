"""Sin referencia propia por link, regenerar un link vencido se rechaza.

Correccion del coordinador sobre perf/f4-pay (2026-09-25). Shifty nunca
estuvo en produccion: no hay links legados en vuelo, asi que
``MERCADOPAGO_LINK_REF_ENABLED`` nace prendido. Y el hueco de pago doble no
puede reabrirse aunque operaciones lo apague: sin nonce por link, un pago
del link viejo no se distingue del nuevo, asi que el unico camino nuevo de
5d41644 que reabre un cobro (regenerar desde el panel el link de un cobro
``expired``) responde 409 ``PAYMENT_LINK_REGENERATION_UNAVAILABLE``, sin
tocar el cobro ni llamar a Mercado Pago.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from core.config import Settings, settings
from modules.payments.model import PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _cobro
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_regenerar_link_de_cobro_vencido import _con_cobro_vencido


def test_la_referencia_propia_por_link_nace_prendida() -> None:
    assert Settings.model_fields["MERCADOPAGO_LINK_REF_ENABLED"].default is True


@pytest.mark.asyncio
async def test_con_el_flag_prendido_regenerar_un_link_vencido_funciona(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "regen-flag-prendido"
    )

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 200, res.text
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.PENDING.value
    assert cobro.preference_id == creadas[-1] != creadas[0]
    assert cobro.link_ref


@pytest.mark.asyncio
async def test_con_el_flag_apagado_regenerar_un_link_vencido_es_409(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "regen-flag-apagado"
    )
    antes = await _cobro(test_session, turno)
    estado_previo = (antes.status, antes.preference_id, antes.link_ref)
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", False)
    llamadas: list[str] = []

    async def mp(*args: Any, **kwargs: Any) -> dict[str, Any]:
        llamadas.append(str(kwargs.get("path")))
        raise AssertionError("no se puede llamar a MP")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_REGENERATION_UNAVAILABLE"
    assert llamadas == []
    despues = await _cobro(test_session, turno)
    assert (despues.status, despues.preference_id, despues.link_ref) == estado_previo
    assert despues.status == PaymentStatus.EXPIRED.value
    assert len(creadas) == 1
