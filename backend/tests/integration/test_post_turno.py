"""Post-turno (Fase 3, 2026-09-10): mail "reserva de nuevo" al completar y
telefono del cliente en la agenda solo para administradores.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.security import hash_password
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon, _reserva, _tienda_reservable


async def _turno_confirmado(
    client: AsyncClient, slug: str, *, email: str = "carla@example.com"
) -> tuple[str, str, str, str, str]:
    store, token, service, staff, slot = await _tienda_reservable(client, slug)
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email=email),
    )
    assert reserva.status_code == 201, reserva.text
    pid = reserva.json()["public_id"]
    confirmar = await client.patch(
        f"/appointments/{pid}/confirm", headers=auth_headers(token)
    )
    assert confirmar.status_code == 200, confirmar.text
    return store, token, service, staff, pid


@pytest.mark.asyncio
async def test_completar_manda_el_mail_de_reserva_de_nuevo_con_deep_link(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    _store, token, service, staff, pid = await _turno_confirmado(client, "rebook")

    completar = await client.patch(
        f"/appointments/{pid}/complete", headers=auth_headers(token)
    )
    assert completar.status_code == 200, completar.text
    assert completar.json()["status"] == "completed"

    destino, asunto, cuerpo = buzon.enviados[-1]
    assert destino == "carla@example.com"
    assert asunto.startswith("Gracias por tu visita")
    assert f"/b/rebook?service={service}&staff={staff}" in cuerpo
    assert "Hola Carla Ruiz" in cuerpo


@pytest.mark.asyncio
async def test_smtp_caido_no_impide_completar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explota(to: str, subject: str, body: str) -> bool:
        raise ConnectionError("smtp down")

    _store, token, _service, _staff, pid = await _turno_confirmado(client, "smtp-caido")
    monkeypatch.setattr(tasks, "_send_email", explota)

    completar = await client.patch(
        f"/appointments/{pid}/complete", headers=auth_headers(token)
    )
    assert completar.status_code == 200, completar.text

    agenda = await client.get(
        "/appointments/search",
        headers=auth_headers(token),
        params={"statuses": "completed"},
    )
    assert agenda.status_code == 200, agenda.text
    assert any(r["public_id"] == pid for r in agenda.json()["results"])


@pytest.mark.asyncio
async def test_con_recordatorios_apagados_no_sale_el_mail_de_reserva_de_nuevo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    _store, token, _service, _staff, pid = await _turno_confirmado(client, "apagado")
    apagar = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"send_email_reminders": False},
    )
    assert apagar.status_code == 200, apagar.text
    antes = len(buzon.enviados)

    completar = await client.patch(
        f"/appointments/{pid}/complete", headers=auth_headers(token)
    )
    assert completar.status_code == 200, completar.text
    assert len(buzon.enviados) == antes


@pytest.mark.asyncio
async def test_el_telefono_del_cliente_solo_lo_ve_el_administrador(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _store, token, _service, staff, pid = await _turno_confirmado(client, "telefono")

    agenda = await client.get(
        "/appointments/search", headers=auth_headers(token), params={"page_size": 50}
    )
    assert agenda.status_code == 200, agenda.text
    fila = next(r for r in agenda.json()["results"] if r["public_id"] == pid)
    # El alta publica guarda el telefono normalizado (solo digitos).
    assert fila["client_phone"] == "5491155550031"

    # El profesional (rol staff) entra con su propio usuario y no ve el telefono.
    profesional = (
        await test_session.execute(select(User).where(User.id == staff))
    ).scalar_one()
    profesional.hashed_password = hash_password("StaffPass123!")
    await test_session.commit()
    login = await client.post(
        "/auth/login",
        json={"email": "pro-demo@test.com", "password": "StaffPass123!"},
    )
    assert login.status_code == 200, login.text
    staff_token = login.json()["access_token"]

    agenda_staff = await client.get(
        "/appointments/search",
        headers=auth_headers(staff_token),
        params={"page_size": 50},
    )
    assert agenda_staff.status_code == 200, agenda_staff.text
    fila_staff = next(
        r for r in agenda_staff.json()["results"] if r["public_id"] == pid
    )
    assert fila_staff["client_phone"] is None
