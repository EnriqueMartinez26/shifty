"""Errores de las compensaciones del link del panel y texto del aviso de duplicado.

Revision de e5579b6..3b977a9 (2026-09-25, #6):

- Si borrar el cobro huerfano (``_discard_orphan_payment``) falla, por
  ejemplo con el ``IntegrityError`` de la carrera con el historial de links
  (otra request anoto un link retirado de ese cobro), ese fallo tapaba el
  error del proveedor que se estaba compensando. Ahora se loguea
  (``panel_link_orphan_discard_failed``) y sale el error ORIGINAL, como en
  ``_drop_unsealed_link_or_log``.
- El aviso de pago duplicado decia "ya estaba pagado" tambien para un cobro
  devuelto; ahora dice "ya tenia un pago registrado".
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

import modules.payments.jobs as jobs
import modules.payments.service as payments_service
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado


@pytest.mark.asyncio
async def test_si_borrar_el_cobro_huerfano_falla_sale_el_error_del_proveedor(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "huerfano-falla", sena=False)
    turno = await _confirmado(client, t, 13)

    async def mp_caido(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("mercado pago caido")

    async def borrar_falla(*_args: Any, **_kwargs: Any) -> None:
        raise IntegrityError(
            "DELETE FROM payments", {}, Exception("payment_link_history_fkey")
        )

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_caido)
    monkeypatch.setattr(payments_service, "_discard_orphan_payment", borrar_falla)

    with capture_logs() as logs:
        res = await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
        )

    # El 502 del proveedor, no el 409 generico del IntegrityError.
    assert res.status_code == 502, res.text
    fallos = [e for e in logs if e["event"] == "panel_link_orphan_discard_failed"]
    assert len(fallos) == 1, logs
    assert fallos[0]["log_level"] == "error"
    assert fallos[0]["appointment_id"] == turno


@pytest.mark.parametrize("duplicado", [True, False])
def test_el_aviso_de_duplicado_no_dice_que_estaba_pagado(duplicado: bool) -> None:
    aviso = jobs._replaced_link_notification(
        OutboxMessage(
            store_id="tienda",
            event_type=NotificationType.PAYMENT_ON_REPLACED_LINK.value,
            payload={
                "appointment_id": "turno",
                "amount": "100",
                "duplicado": duplicado,
            },
        )
    )

    assert aviso is not None
    cuerpo = aviso.body or ""
    # Un cobro devuelto tambien es "duplicado": no estaba pagado.
    assert "ya estaba pagado" not in cuerpo
    if duplicado:
        assert "ya tenia un pago registrado" in cuerpo, cuerpo
