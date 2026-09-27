"""El ticket promedio del resumen se calcula sobre los turnos que cobraron.

2026-09-20, hallazgo AUD2-B5-04: ``total_revenue`` es la plata acreditada,
pero el denominador era ``total_appointments``, o sea TODOS los turnos del
rango sin mirar el estado: cancelados, vencidos y ausentes incluidos. Sintoma:
una tienda con un servicio de $10.000 y muchos ``pending_payment`` que expiran
veia un ticket promedio arbitrariamente bajo y concluia que le bajo el precio.
Son dos universos distintos (plata cobrada / turnos agendados) en una sola
division.

Decision: ``average_ticket = total_revenue / turnos con pago acreditado``, la
misma definicion de ingreso que usa todo el modulo (regla "ingreso = pago
acreditado"). El numerador y el denominador salen ahora de la MISMA consulta.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import AppointmentStatus
from modules.payments.model import PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _tienda
from tests.integration.test_reportes_sena_retenida import DIA, _turno


@pytest.mark.asyncio
async def test_el_ticket_promedio_divide_por_los_turnos_cobrados(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, servicio = await _tienda(client, test_session, "aud2b504")
    acreditado = PaymentStatus.MANUAL_CONFIRMED

    async def turno(
        clave: str,
        hora: int,
        estado: AppointmentStatus,
        pago: tuple[str, PaymentStatus] | None,
    ) -> None:
        await _turno(
            test_session,
            store,
            staff,
            servicio,
            clave=clave,
            hora=hora,
            estado=estado,
            pago=pago,
        )

    await turno("b504-cobrado", 9, AppointmentStatus.COMPLETED, ("10000", acreditado))
    await turno("b504-cancelado-1", 10, AppointmentStatus.CANCELLED, None)
    await turno("b504-cancelado-2", 11, AppointmentStatus.CANCELLED, None)

    res = await client.get(
        "/reports/summary",
        params={"from_date": DIA.isoformat(), "to_date": DIA.isoformat()},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    stats = res.json()["stats"]
    assert stats["total_appointments"] == 3
    assert stats["total_revenue"] == 10000.0
    # Antes: 10000 / 3 == 3333.33, el precio del servicio dividido por los
    # turnos que se cayeron.
    assert stats["average_ticket"] == 10000.0


@pytest.mark.asyncio
async def test_un_rango_sin_un_solo_cobro_no_divide_por_cero(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, servicio = await _tienda(client, test_session, "aud2b504b")
    await _turno(
        test_session,
        store,
        staff,
        servicio,
        clave="b504-sin-cobro",
        hora=9,
        estado=AppointmentStatus.CANCELLED,
        pago=None,
    )
    res = await client.get(
        "/reports/summary",
        params={"from_date": DIA.isoformat(), "to_date": DIA.isoformat()},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["stats"]["average_ticket"] == 0.0
    assert Decimal(str(res.json()["stats"]["total_revenue"])) == Decimal("0")
