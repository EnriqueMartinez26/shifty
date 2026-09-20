"""La sena retenida de un turno cancelado se informa aparte del ingreso por servicio.

2026-09-18, hallazgo B5-10: la regla "ingreso = pago acreditado" estaba
escrita dos veces (``dashboard`` y ``reports``) y la plata acreditada de un
turno CANCELADO entraba en ``total_revenue`` sin distinguirse, mientras
``top_services`` la descartaba: tres numeros distintos para el mismo hecho y
ninguna forma de saber cuanto del ingreso era sena retenida.

Decision (OK global del usuario, sugerencia del brief): la sena no
reembolsada de un turno cancelado ES ingreso, pero categorizada aparte. Campo
NUEVO ``stats.retained_deposit_revenue`` (aditivo): ``total_revenue`` sigue
siendo toda la plata acreditada del rango, y el ingreso por servicio es
``total_revenue - retained_deposit_revenue``.
Un pago reembolsado deja de estar acreditado y no cuenta en ninguno. Todo se
agrega en SQL (regla 11) y acotado a la tienda.

2026-09-20, AUD2-B5-05: este docstring decia que ese ingreso por servicio era
"lo que ya suman top_services" y el test lo afirmaba con ``==``. Es falso:
``top_services`` lleva ``LIMIT 5``. Pasaba porque la semilla tiene UN solo
servicio. La igualdad queda acotada a ese caso y el general vive en
``test_reportes_ingreso_por_servicio.py``.
"""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment, PaymentStatus
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _tienda

DIA = date(2026, 9, 3)


async def _turno(
    session: AsyncSession,
    store: Store,
    staff: Staff,
    servicio: Service,
    *,
    clave: str,
    hora: int,
    estado: AppointmentStatus,
    pago: tuple[str, PaymentStatus] | None,
) -> None:
    cliente = User(
        email=f"cliente-{clave}@b510.test",
        hashed_password="no-se-loguea",
        first_name="Cliente",
        last_name=clave,
        role=UserRole.CLIENT,
        store_id=store.id,
    )
    session.add(cliente)
    await session.flush()
    starts_at = local_to_utc(DIA, time(hora, 0))
    turno = Appointment(
        client_id=cliente.id,
        service_id=servicio.id,
        staff_id=staff.id,
        store_id=store.id,
        client_name="Cliente",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        price_amount=Decimal("10000"),
        status=estado.value,
        idempotency_key=f"b510-{clave}",
    )
    session.add(turno)
    await session.flush()
    if pago is not None:
        session.add(
            Payment(
                store_id=store.id,
                appointment_id=turno.id,
                amount=Decimal(pago[0]),
                status=pago[1].value,
                provider="manual",
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_la_sena_de_un_cancelado_es_ingreso_pero_va_aparte(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, servicio = await _tienda(client, test_session, "b510-a")
    _, otra, staff_otra, servicio_otra = await _tienda(client, test_session, "b510-b")
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

    await turno("completado", 9, AppointmentStatus.COMPLETED, ("10000", acreditado))
    await turno(
        "cancelado-retiene",
        10,
        AppointmentStatus.CANCELLED,
        ("3000", PaymentStatus.APPROVED),
    )
    await turno(
        "cancelado-devuelto",
        11,
        AppointmentStatus.CANCELLED,
        ("2000", PaymentStatus.REFUNDED),
    )
    await turno("cancelado-sin-pago", 12, AppointmentStatus.CANCELLED, None)
    # Otra tienda con una sena retenida: no puede aparecer en la de A.
    await _turno(
        test_session,
        otra,
        staff_otra,
        servicio_otra,
        clave="otra-tienda",
        hora=10,
        estado=AppointmentStatus.CANCELLED,
        pago=("7777", acreditado),
    )

    res = await client.get(
        "/reports/summary",
        params={"from_date": DIA.isoformat(), "to_date": DIA.isoformat()},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    stats = res.json()["stats"]
    # Campo existente, sin cambios: toda la plata acreditada del rango.
    assert stats["total_revenue"] == 13000.0
    # Campo nuevo: la parte que es sena retenida de turnos cancelados.
    assert stats["retained_deposit_revenue"] == 3000.0
    # El ingreso por servicio es la diferencia entre los dos campos. Con UN
    # solo servicio sembrado el top-5 no trunca nada, asi que aca ademas
    # coincide; con mas de cinco no tiene por que (AUD2-B5-05).
    assert len(res.json()["top_services"]) == 1
    por_servicio = sum(s["revenue"] for s in res.json()["top_services"])
    assert por_servicio == stats["total_revenue"] - stats["retained_deposit_revenue"]
