"""Reprogramar desde el portal no devuelve a pendiente un turno confirmado.

Auditoria 2, AUD2-B1-14 (2026-09-20). Sintoma: el turno nuevo nacia siempre
con el estado por defecto de la columna (`pending`), asi que un turno que el
cliente tenia `confirmed` volvia a "pendiente de confirmar" sin que nadie se
enterara: no sale mail al cliente ni notificacion a la tienda, el turno figura
como no confirmado en la agenda y, si nadie lo confirma, el job de expiracion
lo levanta a la hora de inicio (`expires_at = new_starts_at`).

Decision (2026-09-20): el turno movido conserva el estado del original. Puede
hacerlo sin riesgo porque a esta altura no hay sena de por medio: un turno en
`pending_payment` lo frena `reject_cancellation_while_awaiting_payment` y uno
con pago acreditado lo frena `_reject_paid_reschedule`. O sea, lo unico que se
conserva es un `confirmed` sin cobro, y con el se va el `expires_at`: no hay
retencion que vencer sobre un turno ya confirmado.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_caracterizacion_autogestion import (
    TELEFONO,
    _con_turno,
    _turno,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


@pytest.mark.asyncio
async def test_un_turno_confirmado_sigue_confirmado_despues_de_moverlo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "estado-confirmado")
    confirmar = await client.patch(
        f"/appointments/{turno}/confirm", headers=auth_headers(t.token)
    )
    assert confirmar.status_code == 200, confirmar.text
    assert (await _turno(test_session, turno)).status == "confirmed"

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "estado-confirmado-0001",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "confirmed"
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.status == "confirmed"
    # Un turno confirmado no tiene retencion que vencer: sin esto el job de
    # expiracion lo miraba a la hora de inicio.
    assert nuevo.expires_at is None
    assert (await _turno(test_session, turno)).status == "cancelled"


@pytest.mark.asyncio
async def test_un_turno_pendiente_sigue_pendiente_y_conserva_su_retencion(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda del otro lado: mover un pendiente no lo confirma solo."""
    t, turno = await _con_turno(client, monkeypatch, "estado-pendiente")
    nuevo_inicio = t.slot + timedelta(hours=2)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": nuevo_inicio.isoformat(),
            "idempotency_key": "estado-pendiente-0001",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending"
    nuevo = await _turno(test_session, res.json()["public_id"])
    assert nuevo.status == "pending"
    assert nuevo.expires_at is not None
