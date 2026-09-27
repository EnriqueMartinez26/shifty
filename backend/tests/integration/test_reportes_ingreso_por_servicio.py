"""El ingreso por servicio son dos campos del resumen, no la suma del top-5.

2026-09-20, hallazgo AUD2-B5-05: el docstring y el test de B5-10 afirmaban la
identidad ``sum(top_services.revenue) == total_revenue -
retained_deposit_revenue``. ``top_services`` lleva ``LIMIT 5``, asi que esa
igualdad solo se cumple si la tienda tuvo <=5 servicios en el rango; el test la
sembraba con UNO solo, o sea que pasaba por la forma de la semilla y no por la
propiedad. Sintoma: el dueno con 7 servicios resta los dos campos, no le cierra
con la tabla, y la proxima persona lee ese test como especificacion.

La identidad verdadera, y la unica que se afirma aca:
``ingreso por servicio == total_revenue - retained_deposit_revenue``, sobre
TODOS los servicios. ``top_services`` es un ranking de a lo sumo cinco: su suma
es menor o igual, nunca la definicion.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import AppointmentStatus
from modules.payments.model import PaymentStatus
from modules.services.model import Service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _tienda
from tests.integration.test_reportes_sena_retenida import DIA, _turno

COBRO_POR_SERVICIO = Decimal("1000")
SERVICIOS_EXTRA = 6


@pytest.mark.asyncio
async def test_el_top_5_no_agota_el_ingreso_por_servicio(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, primero = await _tienda(client, test_session, "aud2b505")
    servicios = [primero]
    for numero in range(SERVICIOS_EXTRA):
        extra = Service(
            store_id=store.id,
            name=f"Servicio {numero}",
            duration_minutes=30,
            price=Decimal("10000"),
        )
        test_session.add(extra)
        servicios.append(extra)
    await test_session.commit()

    for numero, servicio in enumerate(servicios):
        await _turno(
            test_session,
            store,
            staff,
            servicio,
            clave=f"b505-{numero}",
            hora=8 + numero,
            estado=AppointmentStatus.COMPLETED,
            pago=(str(COBRO_POR_SERVICIO), PaymentStatus.MANUAL_CONFIRMED),
        )

    res = await client.get(
        "/reports/summary",
        params={"from_date": DIA.isoformat(), "to_date": DIA.isoformat()},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    stats = cuerpo["stats"]
    esperado = float(COBRO_POR_SERVICIO * (SERVICIOS_EXTRA + 1))

    # Los dos campos del resumen si cierran: ninguno esta truncado.
    assert stats["total_revenue"] == esperado
    assert stats["retained_deposit_revenue"] == 0.0

    # La tabla, en cambio, es un top-5 y se queda corta. Esta es la asercion
    # que el test de B5-10 hacia con "==" sobre una tienda de un solo servicio.
    assert len(cuerpo["top_services"]) == 5
    por_servicio = sum(s["revenue"] for s in cuerpo["top_services"])
    assert por_servicio < stats["total_revenue"] - stats["retained_deposit_revenue"]
