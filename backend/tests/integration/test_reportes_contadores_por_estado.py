"""Los contadores por estado del resumen cierran contra el total.

2026-09-20, hallazgo AUD2-B5-14: ``_STATUS_COUNTERS`` mapeaba ``completed``,
``cancelled``, ``pending`` (con ``pending_payment`` adentro) y ``confirmed``.
``absent`` y ``expired`` entraban solo en ``total_appointments``. Sintoma: el
dueno ve seis numeros que no suman y ninguna fila "otros" que explique la
diferencia, justo cuando el ausente es el estado que quiere mirar. Ademas
``/reports/professionals`` SI cuenta el ausente
(``_PROFESSIONAL_STATUS_COUNTERS``): los dos reportes de la misma pantalla
usaban vocabularios distintos y el dueno tenia que reconciliar a mano.

Campos NUEVOS y aditivos (default 0, como se hizo con
``retained_deposit_revenue``): ``absent_appointments`` y
``expired_appointments``. Salen del mismo ``GROUP BY status``, sin consulta
extra.
"""

from datetime import time

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import AppointmentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _tienda
from tests.integration.test_reportes_sena_retenida import DIA, _turno

# Los siete estados del grafo, uno por turno. pending_payment cuenta como
# pendiente: para el dueno es el mismo casillero.
ESTADOS = (
    AppointmentStatus.PENDING,
    AppointmentStatus.PENDING_PAYMENT,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.CANCELLED,
    AppointmentStatus.ABSENT,
    AppointmentStatus.EXPIRED,
)
CONTADORES = (
    "completed_appointments",
    "cancelled_appointments",
    "pending_appointments",
    "confirmed_appointments",
    "absent_appointments",
    "expired_appointments",
)


@pytest.mark.asyncio
async def test_los_contadores_por_estado_suman_el_total(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, servicio = await _tienda(client, test_session, "aud2b514")
    for numero, estado in enumerate(ESTADOS):
        await _turno(
            test_session,
            store,
            staff,
            servicio,
            clave=f"b514-{estado.value}",
            hora=8 + numero,
            estado=estado,
            pago=None,
        )

    res = await client.get(
        "/reports/summary",
        params={"from_date": DIA.isoformat(), "to_date": DIA.isoformat()},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    stats = res.json()["stats"]

    assert stats["total_appointments"] == len(ESTADOS)
    assert stats["absent_appointments"] == 1
    assert stats["expired_appointments"] == 1
    assert stats["pending_appointments"] == 2  # pending + pending_payment
    assert sum(stats[nombre] for nombre in CONTADORES) == stats["total_appointments"]
