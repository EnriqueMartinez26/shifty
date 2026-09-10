"""El telefono no prueba identidad: no adopta el contacto de otro (2026-09-10).

Regresion encontrada al revisar la Fase 4: cualquiera que conociera el
telefono de un cliente podia anotarse en la lista de espera (sin OTP, por
diseno) con ese telefono y SU propio email. ``get_or_create_client`` pisaba
el email tecnico del cliente y, desde ahi, todas las notificaciones de esa
persona -- confirmaciones, recordatorios y sus datos de turno -- llegaban al
atacante.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.otp.service import OtpService
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

VICTIMA = "+5491155550999"


async def _tienda(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        store,
        token,
        service,
        staff,
        dia.replace(hour=13, minute=0, second=0, microsecond=0),
    )


async def _email_del_cliente(session: AsyncSession, phone: str) -> str:
    session.expire_all()
    fila = (
        await session.execute(
            select(User).where(User.phone == phone, User.role == UserRole.CLIENT)
        )
    ).scalar_one()
    return str(fila.email)


@pytest.mark.asyncio
async def test_anotarse_en_la_lista_de_espera_no_secuestra_el_email_del_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda(client, "secuestro")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Victima",
            "client_phone": VICTIMA,
            "idempotency_key": "secuestro-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    tecnico = await _email_del_cliente(test_session, "5491155550999")
    assert tecnico.endswith(".noreply")

    alta = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": store,
            "service_id": service,
            "window_starts_at": (slot + timedelta(days=1)).isoformat(),
            "window_ends_at": (slot + timedelta(days=2)).isoformat(),
            "client_name": "Atacante",
            "client_phone": VICTIMA,
            "client_email": "atacante@evil.com",
        },
    )
    assert alta.status_code == 201, alta.text

    assert await _email_del_cliente(test_session, "5491155550999") == tecnico, (
        "el email del cliente no puede cambiarlo un tercero con solo saber el telefono"
    )


@pytest.mark.asyncio
async def test_reservar_sin_otp_no_pisa_el_contacto_pero_si_avisa_a_ese_mail(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, _token, service, staff, slot = await _tienda(client, "secuestro-reserva")

    primera = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Victima",
            "client_phone": VICTIMA,
            "idempotency_key": "secuestro-reserva-01",
        },
    )
    assert primera.status_code == 201, primera.text
    tecnico = await _email_del_cliente(test_session, "5491155550999")

    segunda = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (slot + timedelta(hours=2)).isoformat(),
            "client_name": "Atacante",
            "client_phone": VICTIMA,
            "client_email": "atacante@evil.com",
            "idempotency_key": "secuestro-reserva-02",
        },
    )
    assert segunda.status_code == 201, segunda.text
    assert await _email_del_cliente(test_session, "5491155550999") == tecnico

    # El mail de ESA reserva si va al email que dejaron (es su propia reserva),
    # pero no queda pegado al cliente para las notificaciones futuras.
    assert any(destino == "atacante@evil.com" for destino, _a, _c in buzon.enviados)


@pytest.mark.asyncio
async def test_con_el_telefono_verificado_por_otp_si_se_adopta_el_email(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda(client, "secuestro-otp")

    primera = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Duenio del telefono",
            "client_phone": VICTIMA,
            "idempotency_key": "secuestro-otp-01",
        },
    )
    assert primera.status_code == 201, primera.text

    # El cliente prueba que el telefono es suyo.
    tienda = (
        await test_session.execute(
            select(User).where(User.email == "secuestro-otp@example.com")
        )
    ).scalar_one()
    servicio_otp = OtpService(test_session)
    pedido = await servicio_otp.request_code(
        store_id=tienda.store_id,
        phone="5491155550999",
        channel="email",
        email="real@example.com",
        store_name="Demo",
    )
    verificado = await servicio_otp.verify_code(
        store_id=tienda.store_id,
        phone="5491155550999",
        code=str(pedido["debug_code"]),
    )
    assert verificado

    segunda = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (slot + timedelta(hours=2)).isoformat(),
            "client_name": "Duenio del telefono",
            "client_phone": VICTIMA,
            "client_email": "real@example.com",
            "idempotency_key": "secuestro-otp-02",
        },
    )
    assert segunda.status_code == 201, segunda.text
    assert await _email_del_cliente(test_session, "5491155550999") == "real@example.com"
