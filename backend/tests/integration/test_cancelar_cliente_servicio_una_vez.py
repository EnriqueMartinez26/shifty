"""La cancelacion del cliente lee el servicio del turno una sola vez.

Audit B1-21 (2026-09-18). ``client_cancel_appointment`` hacia el mismo
``select(Service)`` dos veces: antes del commit (para el aviso al duenio por
outbox) y despues (para la respuesta). Consulta redundante en un endpoint
publico; la fila no cambia entre una y otra.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)

TELEFONO = "+5491155550901"


@pytest.mark.asyncio
async def test_cancelar_desde_el_portal_lee_el_servicio_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, token = await register_and_login(
        client, slug="cancel-servicio", email="cancel-servicio@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=13, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cancela",
            # La autogestion exige una ficha con email ENTREGABLE verificado por
            # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
            "client_email": "cancela@example.com",
            "client_phone": TELEFONO,
            "idempotency_key": "cancel-servicio-0001",
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

    lecturas_de_servicio: list[str] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if "FROM services" in str(statement):
            lecturas_de_servicio.append(str(statement)[:60])
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    cancelado = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/cancel",
        json={"phone": TELEFONO},
    )
    monkeypatch.undo()

    assert cancelado.status_code == 200, cancelado.text
    assert cancelado.json()["service_id"] == service
    assert cancelado.json()["service_name"] == "Consulta"
    assert len(lecturas_de_servicio) == 1, lecturas_de_servicio

    # El aviso al duenio sigue llevando el nombre del servicio.
    aviso = (
        await test_session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_type
                == NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value
            )
        )
    ).scalar_one()
    assert aviso.payload["service_name"] == "Consulta"
