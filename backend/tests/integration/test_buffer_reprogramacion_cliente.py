"""La reprogramacion del cliente respeta ``buffer_minutes`` como el alta.

Audit B1-07 (2026-09-17). Sintoma: con ``buffer_minutes=15`` el alta publica
rechazaba un turno pegado al anterior (409), pero el cliente que ya tenia un
turno podia reprogramarlo justo pegado: la consulta de choque de
``client_reschedule_appointment`` no ensanchaba por el buffer de la tienda. La
exclusion GiST no lo atrapa (los rangos no se solapan): el profesional se
quedaba sin el hueco que la tienda configuro.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


@pytest.mark.asyncio
async def test_reprogramar_pegado_al_turno_vecino_respeta_el_buffer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)

    store, token = await register_and_login(
        client, slug="buffer-repro", email="buffer-repro@example.com"
    )
    ajuste = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 15}
    )
    assert ajuste.status_code == 200, ajuste.text
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local

    def reserva(starts_at: datetime, phone: str, key: str) -> dict[str, str]:
        return {
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": starts_at.isoformat(),
            "client_name": "Buffer",
            # La autogestion exige una ficha con email ENTREGABLE verificado por
            # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
            "client_email": f"buffer-{phone.lstrip('+')}@example.com",
            "client_phone": phone,
            "idempotency_key": key,
        }

    # Cliente A: 13:00-13:30. Cliente B: 15:00-15:30 (lejos, entra).
    vecino = await client.post(
        "/public/appointments", json=reserva(base, "+5491155550701", "buffer-a-1")
    )
    assert vecino.status_code == 201, vecino.text
    telefono_b = "+5491155550702"
    propio = await client.post(
        "/public/appointments",
        json=reserva(base + timedelta(hours=2), telefono_b, "buffer-b-1"),
    )
    assert propio.status_code == 201, propio.text
    turno_b = propio.json()["public_id"]

    # El alta publica ya rechaza el horario pegado (contraste con el sintoma).
    pegado_alta = await client.post(
        "/public/appointments",
        json=reserva(base + timedelta(minutes=30), "+5491155550703", "buffer-c-1"),
    )
    assert pegado_alta.status_code == 409, pegado_alta.text

    # B valida su telefono por OTP para autogestionar.
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": telefono_b, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": telefono_b,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text

    # Pegado al turno de A (30 de servicio, 15 de buffer): mismo 409 que el alta.
    pegado = await client.patch(
        f"/public/client/appointments/{turno_b}/reschedule",
        json={
            "phone": telefono_b,
            "new_starts_at": (base + timedelta(minutes=30)).isoformat(),
            "idempotency_key": "buffer-repro-pegado-1",
        },
    )
    assert pegado.status_code == 409, pegado.text

    # Con el buffer respetado: entra.
    separado = await client.patch(
        f"/public/client/appointments/{turno_b}/reschedule",
        json={
            "phone": telefono_b,
            "new_starts_at": (base + timedelta(minutes=45)).isoformat(),
            "idempotency_key": "buffer-repro-separado-1",
        },
    )
    assert separado.status_code == 200, separado.text
