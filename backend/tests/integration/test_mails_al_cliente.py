"""El cliente recibe mail al reservar y al ser confirmado (2026-09-10).

Antes el mail del flujo publico estaba detras de ``status == CONFIRMED`` y el
turno nace pendiente: nunca salia nada. ``confirm()`` tampoco mandaba. Solo
llegaba el recordatorio de 24 horas. Ademas la hora salia en ISO UTC.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from core.utils import ARGENTINA_TZ
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


class Buzon:
    def __init__(self, *, falla: bool = False) -> None:
        self.enviados: list[tuple[str, str, str]] = []
        self.falla = falla

    async def __call__(self, to: str, subject: str, body: str) -> bool:
        if self.falla:
            return False
        self.enviados.append((to, subject, body))
        return True


async def _tienda_reservable(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    return store, token, service, staff, slot


def _reserva(
    store: str, service: str, staff: str, slot: datetime, **extra: str
) -> dict[str, str]:
    cuerpo = {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Carla Ruiz",
        "client_phone": "+5491155550031",
        "idempotency_key": "mail-cliente-000001",
    }
    cuerpo.update(extra)
    return cuerpo


@pytest.mark.asyncio
async def test_reservar_y_confirmar_mandan_mail_en_hora_argentina(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda_reservable(client, "mail-ok")

    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text

    assert len(buzon.enviados) == 1
    destino, asunto, cuerpo = buzon.enviados[0]
    assert destino == "carla@example.com"
    assert asunto.startswith("Reserva registrada")
    assert "Hola Carla Ruiz" in cuerpo
    local = slot.astimezone(ARGENTINA_TZ)
    assert local.strftime("%d/%m/%Y") in cuerpo and "10:00 hs" in cuerpo
    assert "T13:00" not in cuerpo, "la hora no puede salir en ISO UTC"
    assert "desde la app" not in cuerpo
    assert "/b/mail-ok" in cuerpo

    confirmar = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/confirm",
        headers=auth_headers(token),
    )
    assert confirmar.status_code == 200, confirmar.text
    assert len(buzon.enviados) == 2
    _, asunto2, cuerpo2 = buzon.enviados[1]
    assert asunto2.startswith("Turno confirmado")
    assert "10:00 hs" in cuerpo2


@pytest.mark.asyncio
async def test_sin_email_real_no_se_manda_nada(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda_reservable(client, "mail-sin")

    # Sin email: el alta inventa uno tecnico .noreply que no debe recibir nada.
    reserva = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )
    assert reserva.status_code == 201, reserva.text
    await client.patch(
        f"/appointments/{reserva.json()['public_id']}/confirm",
        headers=auth_headers(token),
    )
    assert buzon.enviados == []


@pytest.mark.asyncio
async def test_un_smtp_caido_no_impide_reservar_ni_confirmar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon(falla=True))
    store, token, service, staff, slot = await _tienda_reservable(client, "mail-caido")

    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text
    confirmar = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/confirm",
        headers=auth_headers(token),
    )
    assert confirmar.status_code == 200, confirmar.text
    assert confirmar.json()["status"] == "confirmed"
