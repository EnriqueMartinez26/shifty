"""El turno que nace al reprogramar desde el portal lleva ``expires_at``.

Audit B1-22 (2026-09-18). El alta publica fija ``expires_at = starts_at`` en
un turno sin cobro online (el job de expiracion lo levanta si nadie lo
confirma), pero ``client_reschedule_appointment`` creaba el turno nuevo sin
``expires_at``: un ``pending`` de un horario ya pasado quedaba vivo para
siempre y seguia contando como activo en las consultas de choque.

Decision (OK global del usuario, sugerencia del brief): mismo criterio de
``expires_at`` que el alta.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)

TELEFONO = "+5491155553001"


@pytest.mark.asyncio
async def test_el_turno_reprogramado_expira_como_uno_del_alta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, token = await register_and_login(
        client, slug="repro-expira", email="repro-expira@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "client_name": "Expira",
            "client_phone": TELEFONO,
            "idempotency_key": "repro-expira-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text

    nuevo_inicio = base + timedelta(hours=2)
    reprogramado = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": nuevo_inicio.isoformat(),
            "idempotency_key": "repro-expira-nuevo-0001",
        },
    )
    assert reprogramado.status_code == 200, reprogramado.text

    test_session.expire_all()
    original, nuevo = (
        (
            await test_session.execute(
                select(Appointment)
                .where(
                    Appointment.id.in_(
                        [reserva.json()["public_id"], reprogramado.json()["public_id"]]
                    )
                )
                .order_by(Appointment.starts_at.asc())
            )
        )
        .scalars()
        .all()
    )
    # El original (del alta) ya lo tenia; el reprogramado nacia en NULL.
    assert original.expires_at is not None
    assert nuevo.expires_at is not None, "el turno reprogramado no expira nunca"
    assert ensure_utc_aware(nuevo.expires_at) == nuevo_inicio
