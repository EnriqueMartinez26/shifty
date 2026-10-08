"""El ingreso de reportes, panel y conciliacion incluye el resto registrado.

Saldo restante por turno (opcion A, D-20261008-01): una sena acreditada de
$960 sobre un turno de $3.200 mas el resto de $2.240 pagado en el local son
$3.200 de ingreso de UN turno cobrado. Antes de esto cada consulta de ingreso
sumaba solo ``Payment.amount`` acreditado: el resto no existia para reportes,
panel ni conciliacion y el ticket promedio salia de $960.

Toda suma va en SQL (regla 11) y sin multiplicar filas: a lo sumo un resto
vivo por turno (indice unico parcial), igual que un cobro por turno. Un resto
revertido deja de contar.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import today_local
from modules.appointments.model import AppointmentStatus
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda


async def _turno_con_sena_y_resto(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[str, str]:
    token, store, staff, servicio = await _tienda(client, session, slug)
    semilla = _Semilla(session, store, staff)
    ana = semilla.cliente("Ana", "Resto")
    await session.commit()
    turno = await semilla.turno(
        f"{slug}-1",
        today_local(),
        time(10, 0),
        servicio,
        ana,
        AppointmentStatus.COMPLETED,
        precio=Decimal("3200"),
        pago=(Decimal("960"), PaymentStatus.APPROVED),
    )
    res = await client.post(
        f"/payments/{turno}/remaining-payment",
        headers=auth_headers(token),
        json={"idempotency_key": f"{slug}-resto-0001", "method": "efectivo"},
    )
    assert res.status_code == 201, res.text
    assert Decimal(res.json()["amount"]) == Decimal("2240")
    return token, turno


async def _resumen(client: AsyncClient, token: str) -> dict[str, object]:
    hoy = today_local().isoformat()
    res = await client.get(
        "/reports/summary",
        params={"from_date": hoy, "to_date": hoy},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    return dict(res.json())


@pytest.mark.asyncio
async def test_sena_mas_resto_es_el_precio_y_un_solo_turno_cobrado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, _ = await _turno_con_sena_y_resto(client, test_session, "rep-resto")

    resumen = await _resumen(client, token)

    stats = resumen["stats"]
    assert isinstance(stats, dict)
    assert stats["total_revenue"] == 3200
    # Ticket promedio = ingreso / turnos cobrados: 1 turno, no 2 filas.
    assert stats["average_ticket"] == 3200
    assert stats["retained_deposit_revenue"] == 0
    top_servicios = resumen["top_services"]
    assert isinstance(top_servicios, list)
    assert top_servicios[0]["revenue"] == 3200
    top_clientes = resumen["top_clients"]
    assert isinstance(top_clientes, list)
    assert top_clientes[0]["revenue"] == 3200

    hoy = today_local().isoformat()
    profesionales = await client.get(
        "/reports/professionals",
        params={"from_date": hoy, "to_date": hoy},
        headers=auth_headers(token),
    )
    assert profesionales.status_code == 200, profesionales.text
    (fila,) = [
        p for p in profesionales.json()["professionals"] if p["appointments"] > 0
    ]
    assert fila["revenue"] == 3200


@pytest.mark.asyncio
async def test_el_panel_cuenta_el_resto_en_el_ingreso_de_la_semana(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, _ = await _turno_con_sena_y_resto(client, test_session, "panel-resto")

    res = await client.get("/dashboard/summary", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    assert res.json()["stats"]["weekly_revenue"] == 3200


@pytest.mark.asyncio
async def test_la_conciliacion_suma_el_resto_a_lo_acreditado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, _ = await _turno_con_sena_y_resto(client, test_session, "conc-resto")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text

    res = await client.get(
        "/payments/reconciliation/summary", headers=auth_headers(token)
    )

    assert res.status_code == 200, res.text
    assert Decimal(str(res.json()["total_approved_amount"])) == Decimal("3200")


@pytest.mark.asyncio
async def test_un_resto_revertido_deja_de_contar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, turno = await _turno_con_sena_y_resto(client, test_session, "rev-resto")
    revertido = await client.post(
        f"/payments/{turno}/remaining-payment/revert", headers=auth_headers(token)
    )
    assert revertido.status_code == 200, revertido.text

    stats = (await _resumen(client, token))["stats"]
    assert isinstance(stats, dict)
    assert stats["total_revenue"] == 960
    panel = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert panel.json()["stats"]["weekly_revenue"] == 960


@pytest.mark.asyncio
async def test_el_resto_cuenta_aunque_la_sena_se_haya_devuelto(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La sena devuelta deja de ser ingreso; el resto cobrado en el local no.
    El turno sigue contando una vez como cobrado (ticket = resto)."""
    token, turno = await _turno_con_sena_y_resto(client, test_session, "dev-resto")
    test_session.expire_all()
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    assert cobro.apply_status(PaymentStatus.REFUNDED.value)
    await test_session.commit()

    stats = (await _resumen(client, token))["stats"]
    assert isinstance(stats, dict)
    assert stats["total_revenue"] == 2240
    assert stats["average_ticket"] == 2240
