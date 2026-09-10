"""Recursos que no son personas: canchas, salas, boxes (Fase 2, 2026-09-10).

Antes crear un "profesional" exigia email unico global y creaba un usuario
con login: una cancha necesitaba un email inventado. ``kind='resource'`` no
crea usuario ni exige email y reutiliza toda la maquinaria (disponibilidad,
lock, exclusion, bloqueos) que ya estaba indexada por staff_id.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    register_and_login,
)


async def _usuarios(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(User))).scalar_one()
    )


@pytest.mark.asyncio
async def test_un_recurso_no_exige_email_ni_crea_usuario(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="cancha", email="cancha@example.com"
    )
    service = await create_service(client, token)
    antes = await _usuarios(test_session)

    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"kind": "resource", "display_name": "Cancha 2", "service_ids": [service]},
    )
    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["kind"] == "resource"
    assert cuerpo["email"] is None
    assert cuerpo["display_name"] == "Cancha 2"
    assert await _usuarios(test_session) == antes, "un recurso no crea usuario"

    listado = await client.get("/staff/", headers=auth_headers(token))
    assert any(m["public_id"] == cuerpo["public_id"] for m in listado.json())


@pytest.mark.asyncio
async def test_una_persona_sigue_exigiendo_nombre_y_email(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="persona", email="persona@example.com"
    )
    sin_email = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"display_name": "Ana", "first_name": "Ana", "last_name": "Perez"},
    )
    assert sin_email.status_code == 422, sin_email.text
    sin_nombre = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"display_name": "Ana", "email": "ana-persona@example.com"},
    )
    assert sin_nombre.status_code == 422, sin_nombre.text


@pytest.mark.asyncio
async def test_se_reserva_una_cancha_por_el_flujo_publico_y_el_mail_dice_en(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    enviados: list[tuple[str, str, str]] = []

    async def buzon(to: str, subject: str, body: str) -> bool:
        enviados.append((to, subject, body))
        return True

    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token = await register_and_login(
        client, slug="padel", email="padel@example.com"
    )
    service = await create_service(client, token)
    cancha = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"kind": "resource", "display_name": "Cancha 1", "service_ids": [service]},
    )
    cancha_id = cancha.json()["public_id"]
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, cancha_id, target_date=dia)

    publico = await client.get("/public/staff", params={"store_public_id": store})
    assert publico.status_code == 200, publico.text
    assert publico.json()[0]["kind"] == "resource"
    assert publico.json()[0]["display_name"] == "Cancha 1"

    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": cancha_id,
            "starts_at": slot.isoformat(),
            "client_name": "Lucas",
            "client_email": "lucas@example.com",
            "client_phone": "+5491155550088",
            "idempotency_key": "padel-cancha-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    registrada = next(e for e in enviados if e[1].startswith("Reserva registrada"))
    assert "en Cancha 1" in registrada[2]
    assert "con Cancha 1" not in registrada[2]

    # Dos reservas en la misma cancha al mismo horario: la segunda choca.
    choque = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": cancha_id,
            "starts_at": slot.isoformat(),
            "client_name": "Otro",
            "client_phone": "+5491155550089",
            "idempotency_key": "padel-cancha-000002",
        },
    )
    assert choque.status_code == 409, choque.text


@pytest.mark.asyncio
async def test_editar_y_dar_de_baja_un_recurso_no_toca_usuarios(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(client, slug="sala", email="sala@example.com")
    creado = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"kind": "resource", "display_name": "Sala A"},
    )
    pid = creado.json()["public_id"]
    antes = await _usuarios(test_session)

    editado = await client.patch(
        f"/staff/{pid}", headers=auth_headers(token), json={"display_name": "Sala B"}
    )
    assert editado.status_code == 200, editado.text
    assert editado.json()["display_name"] == "Sala B"
    assert editado.json()["kind"] == "resource"

    baja = await client.delete(f"/staff/{pid}", headers=auth_headers(token))
    assert baja.status_code == 204, baja.text
    assert await _usuarios(test_session) == antes
    listado = await client.get("/staff/", headers=auth_headers(token))
    assert all(m["public_id"] != pid for m in listado.json())
