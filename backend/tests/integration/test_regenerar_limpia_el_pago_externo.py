"""Regenerar el link limpia el ``external_payment_id`` del link viejo.

Revision de perf/f4-pay (2026-09-25, #4). El cobro guarda el id del pago de
MP que le llego (``external_payment_id``). Al regenerar el link, ese id es de
un intento sobre el link VIEJO: la conciliacion y el rescate del job de
vencimiento consultan a MP por ese id si esta puesto, asi que seguian
mirando el pago viejo (que ademas ya no pasa la integridad) en vez de buscar
los pagos del link vigente por su referencia.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from core.config import settings
from modules.payments.jobs import reconcile_pending_payments
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _cobro
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_regenerar_link_de_cobro_vencido import _con_cobro_vencido


@pytest.mark.asyncio
async def test_regenerar_limpia_el_pago_externo_y_la_conciliacion_busca_el_link_nuevo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    t, turno, _creadas = await _con_cobro_vencido(
        client, test_session, monkeypatch, "regen-limpia-externo"
    )
    cobro = await _cobro(test_session, turno)
    cobro.external_payment_id = "mp-intento-viejo"
    await test_session.commit()

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert res.status_code == 200, res.text
    cobro = await _cobro(test_session, turno)
    assert cobro.external_payment_id is None
    referencia = cobro.current_external_reference

    consultas: list[str] = []

    async def mp(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        consultas.append(path)
        return {"results": []}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    await reconcile_pending_payments(test_session)

    assert "/v1/payments/mp-intento-viejo" not in consultas, consultas
    assert any(
        c.startswith("/v1/payments/search") and referencia.split(":")[0] in c
        for c in consultas
    ), consultas
