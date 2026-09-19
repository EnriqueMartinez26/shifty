"""El motivo que deja el cliente al cancelar le llega al duenio.

Audit B1-23 (2026-09-18). ``ClientCancelRequest.reason`` se aceptaba y nunca
se leia: aparentaba un "motivo de cancelacion" que el duenio no recibia por
ningun canal, y era el unico texto libre publico del modulo sin
``reject_control_chars`` (regla 19).

Decision (OK global del usuario, sugerencia del brief): el motivo pasa por
``reject_control_chars``, se normaliza a una linea (sin CR/LF) y viaja en el
outbox de la cancelacion; el aviso al duenio (notificacion del panel y mail)
lo muestra como "Motivo: ...". El asunto del mail sigue fijo.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from modules.notifications.model import Notification, NotificationType
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

TELEFONO = "+5491155554001"


@pytest.mark.asyncio
@pytest.mark.parametrize("motivo", ["con\x00nul", "con \u202e bidi", "cero\u200bancho"])
async def test_un_motivo_con_caracteres_de_control_se_rechaza(
    client: AsyncClient, motivo: str
) -> None:
    res = await client.patch(
        "/public/client/appointments/01J0000000000000000000TEST/cancel",
        json={"phone": TELEFONO, "reason": motivo},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_el_motivo_llega_al_duenio_en_una_linea_y_el_asunto_no_cambia(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token = await register_and_login(
        client, slug="motivo-cancel", email="motivo-cancel@example.com"
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
            "client_name": "Motivo",
            "client_phone": TELEFONO,
            "idempotency_key": "motivo-cancel-0001",
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

    cancelado = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/cancel",
        json={
            "phone": TELEFONO,
            "reason": "Me surgio\r\nun viaje\nBcc: otro@example.com",
        },
    )
    assert cancelado.status_code == 200, cancelado.text

    evento = (
        await test_session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_type
                == NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value
            )
        )
    ).scalar_one()
    motivo = "Me surgio un viaje Bcc: otro@example.com"
    assert evento.payload["reason"] == motivo

    antes = len(buzon.enviados)
    await process_outbox_batch(test_session)

    aviso = (
        await test_session.execute(
            select(Notification).where(
                Notification.type
                == NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value
            )
        )
    ).scalar_one()
    assert f"Motivo: {motivo}" in (aviso.body or "")
    assert aviso.title == "Un cliente cancelo su turno"

    asunto = "Shifty - Un cliente cancelo su turno"
    mails = [m for m in buzon.enviados[antes:] if m[1] == asunto]
    assert mails, f"el duenio no recibio el mail: {buzon.enviados[antes:]}"
    destino, _asunto, cuerpo = mails[0]
    assert destino == "motivo-cancel@example.com"
    # El asunto es fijo: el motivo no llega ahi, ni con los saltos de linea.
    assert all(
        "surgio" not in m[1] and "\n" not in m[1] and "\r" not in m[1]
        for m in buzon.enviados
    )
    assert f"Motivo: {motivo}" in cuerpo
