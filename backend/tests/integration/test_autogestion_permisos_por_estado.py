"""Mis turnos: ``can_cancel`` y ``can_reschedule`` dicen lo que hacen las acciones.

2026-09-24. Sintoma (revision funcional del front): el historial del cliente
(``GET /public/client/{store}/{phone}/appointments``) mostraba "Cambiar" y
"Cancelar" en turnos con pago pendiente (``pending_payment``) o con la sena
ya acreditada, y la accion respondia 409 ``PAYMENT_APPOINTMENT_REQUIRES_RELEASE``
o ``PAID_APPOINTMENT_RESCHEDULE_DENIED``, el primero con un mensaje escrito
para administradores. Los flags repetian a mano parte de las reglas
(``can_reschedule`` era ``can_cancel``).

Ahora los flags salen de las MISMAS funciones que usan las acciones
(``client_cancel_denial`` / ``client_reschedule_denial`` y el grafo de
estados): un flag en true es una accion que no rebota por el estado del
turno. El 409 que ve el cliente tiene un mensaje para el cliente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from modules.stores.model import Store
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno

LEJOS = timedelta(days=5)


async def _turno_en_estado(
    session: AsyncSession,
    base_id: str,
    estado: str,
    *,
    en: timedelta = LEJOS,
    pago: PaymentStatus | None = None,
) -> str:
    """Copia del turno reservado, en otro horario y estado (misma ficha)."""
    base = (
        await session.execute(select(Appointment).where(Appointment.id == base_id))
    ).scalar_one()
    inicio = datetime.now(timezone.utc).replace(microsecond=0) + en
    turno = Appointment(
        store_id=base.store_id,
        staff_id=base.staff_id,
        service_id=base.service_id,
        client_id=base.client_id,
        client_name=base.client_name,
        client_email=base.client_email,
        client_phone=base.client_phone,
        starts_at=inicio,
        ends_at=inicio + timedelta(minutes=30),
        duration_minutes=30,
        price_amount=Decimal("10000"),
        status=estado,
    )
    session.add(turno)
    await session.flush()
    if pago is not None:
        session.add(
            Payment(
                store_id=base.store_id,
                appointment_id=turno.id,
                amount=Decimal("2500"),
                status=pago.value,
                provider="manual",
            )
        )
    await session.commit()
    return str(turno.id)


async def _flags(client: AsyncClient, store: str) -> dict[str, tuple[bool, bool]]:
    res = await client.get(f"/public/client/{store}/{TELEFONO}/appointments")
    assert res.status_code == 200, res.text
    return {
        item["public_id"]: (item["can_cancel"], item["can_reschedule"])
        for item in res.json()["appointments"]
    }


@pytest.mark.asyncio
async def test_los_flags_siguen_las_reglas_de_cada_estado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, pendiente = await _con_turno(client, monkeypatch, "flags-estados")
    await test_session.execute(
        update(Store).where(Store.public_id == t.store).values(cancellation_hours=2)
    )
    await test_session.commit()
    casos: dict[str, tuple[bool, bool]] = {pendiente: (True, True)}
    for estado, en, pago, esperado in (
        ("confirmed", LEJOS + timedelta(hours=1), None, (True, True)),
        (
            "confirmed",
            LEJOS + timedelta(hours=2),
            PaymentStatus.APPROVED,
            (True, False),
        ),
        (
            "confirmed",
            LEJOS + timedelta(hours=3),
            PaymentStatus.MANUAL_CONFIRMED,
            (True, False),
        ),
        # Un pago devuelto ya no bloquea: vuelve a poder reprogramarse.
        ("confirmed", LEJOS + timedelta(hours=4), PaymentStatus.REFUNDED, (True, True)),
        ("pending_payment", LEJOS + timedelta(hours=5), None, (False, False)),
        # Dentro de la ventana de cancelacion de la tienda (2 h).
        ("confirmed", timedelta(hours=1), None, (False, False)),
        ("cancelled", LEJOS + timedelta(hours=6), None, (False, False)),
        ("expired", LEJOS + timedelta(hours=7), None, (False, False)),
        ("completed", -timedelta(days=1), None, (False, False)),
        ("absent", -timedelta(days=2), None, (False, False)),
    ):
        turno = await _turno_en_estado(
            test_session, pendiente, estado, en=en, pago=pago
        )
        casos[turno] = esperado

    assert await _flags(client, t.store) == casos


@pytest.mark.asyncio
async def test_pago_pendiente_409_con_mensaje_para_el_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, base = await _con_turno(client, monkeypatch, "flags-pago-pendiente")
    turno = await _turno_en_estado(test_session, base, "pending_payment")

    cancelar = await client.patch(
        f"/public/client/appointments/{turno}/cancel", json={"phone": TELEFONO}
    )
    reprogramar = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "flags-pago-pendiente-1",
        },
    )

    for res in (cancelar, reprogramar):
        assert res.status_code == 409, res.text
        cuerpo: dict[str, Any] = res.json()
        assert cuerpo["error_code"] == "PAYMENT_APPOINTMENT_REQUIRES_RELEASE"
        assert "administrador" not in cuerpo["message"].lower()
        assert "tienda" in cuerpo["message"].lower()


@pytest.mark.asyncio
async def test_turno_pagado_se_cancela_pero_no_se_reprograma(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, base = await _con_turno(client, monkeypatch, "flags-pagado")
    turno = await _turno_en_estado(
        test_session, base, "confirmed", pago=PaymentStatus.APPROVED
    )

    reprogramar = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "flags-pagado-reprogramar",
        },
    )
    cancelar = await client.patch(
        f"/public/client/appointments/{turno}/cancel", json={"phone": TELEFONO}
    )

    assert reprogramar.status_code == 409, reprogramar.text
    assert reprogramar.json()["error_code"] == "PAID_APPOINTMENT_RESCHEDULE_DENIED"
    assert cancelar.status_code == 200, cancelar.text
