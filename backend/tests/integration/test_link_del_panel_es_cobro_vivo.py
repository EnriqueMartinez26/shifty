"""Un link de pago vivo deja el turno "con pago en curso" para el cliente.

Decision del dueno (2026-09-25, D1). Sintoma: el dueno genera un link de pago
desde el panel (``POST /payments/preferences/{id}``) sobre un turno
CONFIRMADO; el turno sigue confirmado y el cliente podia cancelarlo o
reprogramarlo desde "Mis turnos" con el link de Mercado Pago vivo: podia
pagar un turno que ya no existia. La guarda del cliente
(``awaits_payment``) solo miraba ``status == pending_payment``.

Ahora un turno tiene cobro vivo si esta en ``pending_payment`` O tiene un
``Payment`` en ``PENDING`` (``LIVE_CHARGE_PAYMENT_STATUSES``): el cliente no
lo cancela ni lo reprograma (409 ``PAYMENT_APPOINTMENT_REQUIRES_RELEASE`` con
el mensaje para el cliente) y el historial lo muestra sin "Cancelar" ni
"Cambiar". Un cobro vencido, rechazado o devuelto no es un cobro vivo.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_autogestion_permisos_por_estado import (
    LEJOS,
    _flags,
    _turno_en_estado,
)
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


async def _con_cobro(
    session: AsyncSession, turno_id: str, estado: PaymentStatus
) -> None:
    """Cobro del turno como lo deja el panel: con link real de MP."""
    turno = (
        await session.execute(select(Appointment).where(Appointment.id == turno_id))
    ).scalar_one()
    session.add(
        Payment(
            store_id=turno.store_id,
            appointment_id=turno.id,
            amount=Decimal("2500"),
            status=estado.value,
            preference_id=f"pref-vivo-{turno_id[-6:]}",
            payment_link="https://www.mercadopago.com/checkout?pref=vivo",
        )
    )
    await session.commit()


def _cancelar(turno: str) -> dict[str, Any]:
    return {
        "url": f"/public/client/appointments/{turno}/cancel",
        "json": {"phone": TELEFONO},
    }


@pytest.mark.asyncio
async def test_los_flags_del_historial_miran_el_cobro_vivo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, base = await _con_turno(client, monkeypatch, "vivo-flags")
    casos: dict[str, tuple[bool, bool]] = {base: (True, True)}
    for i, (estado_turno, cobro, esperado) in enumerate(
        (
            # El link del panel sobre un confirmado: cobro vivo.
            ("confirmed", PaymentStatus.PENDING, (False, False)),
            ("pending", PaymentStatus.PENDING, (False, False)),
            # Un link vencido o un intento rechazado no son un cobro vivo.
            ("confirmed", PaymentStatus.EXPIRED, (True, True)),
            ("confirmed", PaymentStatus.REJECTED, (True, True)),
            ("confirmed", PaymentStatus.REFUNDED, (True, True)),
        ),
        start=1,
    ):
        turno = await _turno_en_estado(
            test_session, base, estado_turno, en=LEJOS + timedelta(hours=i)
        )
        await _con_cobro(test_session, turno, cobro)
        casos[turno] = esperado

    assert await _flags(client, t.store) == casos


@pytest.mark.asyncio
async def test_el_cliente_no_cancela_ni_reprograma_un_turno_con_link_vivo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, base = await _con_turno(client, monkeypatch, "vivo-acciones")
    turno = await _turno_en_estado(test_session, base, "confirmed")
    await _con_cobro(test_session, turno, PaymentStatus.PENDING)

    cancelar = await client.patch(**_cancelar(turno))
    reprogramar = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "vivo-acciones-reprogramar-1",
        },
    )

    for res in (cancelar, reprogramar):
        assert res.status_code == 409, res.text
        cuerpo: dict[str, Any] = res.json()
        assert cuerpo["error_code"] == "PAYMENT_APPOINTMENT_REQUIRES_RELEASE"
        assert "administrador" not in cuerpo["message"].lower()
        assert "tienda" in cuerpo["message"].lower()
    test_session.expire_all()
    quedo = (
        await test_session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert quedo.status == "confirmed"


@pytest.mark.asyncio
async def test_con_el_link_vencido_el_cliente_vuelve_a_poder_cancelar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, base = await _con_turno(client, monkeypatch, "vivo-vencido")
    turno = await _turno_en_estado(test_session, base, "confirmed")
    await _con_cobro(test_session, turno, PaymentStatus.EXPIRED)

    res = await client.patch(**_cancelar(turno))

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_el_link_generado_desde_el_panel_frena_al_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El caso del dueno de punta a punta: link del panel sobre un confirmado."""
    t, base = await _con_turno(client, monkeypatch, "vivo-panel")
    turno = await _turno_en_estado(test_session, base, "confirmed")

    async def mp(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST" and path == "/checkout/preferences"
        return {
            "id": "pref-panel-d1",
            "init_point": "https://www.mercadopago.com/checkout?pref=panel-d1",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    for metodo, url, cuerpo in (
        ("PUT", "/stores/me/feature-flags", {"payments": True}),
        ("PUT", "/payments/gateway-config", {"access_token": "TEST-D1-TOKEN"}),
    ):
        res = await client.request(
            metodo, url, headers=auth_headers(t.token), json=cuerpo
        )
        assert res.status_code == 200, res.text
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.token)
    )
    assert link.status_code == 200, link.text

    res = await client.patch(**_cancelar(turno))

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "PAYMENT_APPOINTMENT_REQUIRES_RELEASE"
    assert (await _flags(client, t.store))[turno] == (False, False)
