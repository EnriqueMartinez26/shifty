"""Los caminos de falla de la fase 2 del link del panel no dejan un link vivo.

Revision de perf/f4-pay (2026-09-25, #3). Dos caminos que no tenian test:

- Choque de version DESPUES de que Mercado Pago creo la preferencia nueva
  (otra escritura toco el cobro mientras MP respondia): el rollback dejaba la
  preferencia nueva viva en MP sin que nadie la registrara. Ahora se manda a
  vencer (``payment.preference.expire``) antes de responder.
- Falla de Mercado Pago al regenerar el link de un cobro vencido: el cobro
  queda ``expired`` con el placeholder (no hay cobro vivo sin link) y el
  vencimiento del link VIEJO, publicado en la fase 1, queda commiteado.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.payments.model import Payment, PaymentStatus, is_placeholder_preference_id
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_regenerar_link_de_cobro_vencido import _con_cobro_vencido


@pytest.mark.asyncio
async def test_si_la_fase_2_choca_con_la_version_el_link_nuevo_se_vence(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "fase2-version"
    )

    async def mp_mientras_otro_toca_el_cobro(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST"
        # Otra escritura del cobro commiteada mientras MP respondia.
        await test_session.execute(
            update(Payment)
            .where(Payment.appointment_id == turno)
            .values(version=Payment.version + 1)
            .execution_options(synchronize_session=False)
        )
        await AsyncSession.commit(test_session)
        creadas.append("pref-fase2-huerfana")
        return {
            "id": "pref-fase2-huerfana",
            "init_point": "https://www.mercadopago.com/checkout?pref=huerfana",
        }

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", mp_mientras_otro_toca_el_cobro
    )

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    cobro = await _cobro(test_session, turno)
    assert cobro.preference_id != "pref-fase2-huerfana"
    vencidas = [
        e.payload["preference_id"] for e in await _vencimientos(test_session, turno)
    ]
    assert "pref-fase2-huerfana" in vencidas


@pytest.mark.asyncio
async def test_si_mp_falla_al_regenerar_el_cobro_queda_vencido_con_placeholder(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno, creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "fase2-mp-caido"
    )
    (vieja,) = creadas

    async def mp_caido(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("mercado pago caido")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_caido)

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 502, res.text
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.EXPIRED.value
    assert is_placeholder_preference_id(cobro.preference_id)
    assert vieja in [
        e.payload["preference_id"] for e in await _vencimientos(test_session, turno)
    ]
