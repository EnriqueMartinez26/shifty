"""El link de pago del panel solo se genera sobre un turno vivo, y bajo su lock.

Decision del coordinador sobre perf/f4-pay (2026-09-25, #3 del reporte).
Sintoma: ``POST /payments/preferences/{id}`` leia el turno sin lock y sin
mirar su estado: generaba un link de Mercado Pago sobre un turno cancelado,
completado o vencido, y competia con la cancelacion (del cliente o del
personal) sin orden de locks.

Ahora:
- lockea el turno primero (orden turno -> pago, regla 7) y rechaza un turno
  soltado (``cancelled``, ``expired``) con 409 ``APPOINTMENT_NOT_PAYABLE`` sin
  crear cobro. ``completed`` y ``absent`` se siguen pudiendo cobrar, como
  antes de esta rama (correccion de alcance del coordinador).
- la fase 2 (despues de hablar con MP, sin lock) vuelve a lockear el turno
  antes de sellar el link: si en el medio lo cancelaron, no sella nada, manda
  a vencer en MP el link recien creado (``payment.preference.expire``) y
  responde 409. Nunca queda un link vivo sobre un turno cancelado.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _tienda,
    _Tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


async def _confirmado(client: AsyncClient, t: _Tienda, hora: int) -> str:
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.admin),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.dia.replace(
                hour=hora, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Link",
            "client_phone": f"+54911558{hora:05d}",
            "idempotency_key": f"link-vivo-{t.store}-{hora}",
        },
    )
    assert alta.status_code == 201, alta.text
    return str(alta.json()["public_id"])


async def _cobros(session: AsyncSession, turno: str) -> list[Payment]:
    session.expire_all()
    return list(
        (await session.execute(select(Payment).where(Payment.appointment_id == turno)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["cancelled", "expired"])
async def test_sobre_un_turno_soltado_no_hay_link(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"link-terminal-{estado}", sena=False)
    turno = await _confirmado(client, t, 13)
    await test_session.execute(
        update(Appointment).where(Appointment.id == turno).values(status=estado)
    )
    await test_session.commit()

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"
    assert await _cobros(test_session, turno) == []
    assert t.llamadas_mp == []


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["confirmed", "completed", "absent"])
async def test_sobre_un_turno_no_soltado_hay_link(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    """Antes de esta rama el link se generaba sobre cualquier turno; cobrar
    por link un turno ya atendido (``completed``) o ausente sigue igual
    (correccion de alcance del coordinador, 2026-09-25)."""
    t = await _tienda(client, monkeypatch, f"link-vivo-{estado}", sena=False)
    turno = await _confirmado(client, t, 13)
    await test_session.execute(
        update(Appointment).where(Appointment.id == turno).values(status=estado)
    )
    await test_session.commit()

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 200, res.text
    (cobro,) = await _cobros(test_session, turno)
    assert cobro.status == PaymentStatus.PENDING.value


@pytest.mark.asyncio
async def test_cancelado_mientras_se_habla_con_mp_no_se_sella_y_se_vence(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La cancelacion del personal entra entre la fase 1 y el sellado."""
    t = await _tienda(client, monkeypatch, "link-carrera", sena=False)
    turno = await _confirmado(client, t, 13)

    async def mp_mientras_cancelan(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST"
        # Lo que deja la cancelacion del personal (D2): turno cancelado y
        # cobro vencido, commiteados mientras MP responde.
        await test_session.execute(
            update(Appointment)
            .where(Appointment.id == turno)
            .values(status="cancelled")
            .execution_options(synchronize_session=False)
        )
        await test_session.execute(
            update(Payment)
            .where(Payment.appointment_id == turno)
            .values(status="expired", version=Payment.version + 1)
            .execution_options(synchronize_session=False)
        )
        await AsyncSession.commit(test_session)
        return {
            "id": "pref-link-carrera",
            "init_point": "https://www.mercadopago.com/checkout?pref=carrera",
        }

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", mp_mientras_cancelan
    )

    res = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"
    (cobro,) = await _cobros(test_session, turno)
    assert cobro.status == PaymentStatus.EXPIRED.value
    assert cobro.preference_id != "pref-link-carrera", "el link no se sella"
    eventos = await _vencimientos(test_session, turno)
    assert [e.payload["preference_id"] for e in eventos] == ["pref-link-carrera"]
