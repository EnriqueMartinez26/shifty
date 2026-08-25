"""Dashboard y bloqueos de agenda.

Dos modulos con endpoints administrativos poco cubiertos. Los bloqueos ademas
compiten con los turnos por el mismo horario, asi que su interaccion importa.
"""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


@pytest.mark.asyncio
async def test_dashboard_responde_sin_datos(client: AsyncClient) -> None:
    """Una tienda recien creada tiene que ver su panel, no un error."""
    _, token = await register_and_login(
        client, slug="panel-vacio", email="panel-vacio@test.com"
    )
    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), dict)


@pytest.mark.asyncio
async def test_dashboard_exige_autenticacion(client: AsyncClient) -> None:
    res = await client.get("/dashboard/summary")
    assert res.status_code in {401, 403}


@pytest.mark.asyncio
async def test_crear_listar_editar_y_borrar_un_bloqueo(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="bloqueos-crud", email="bloqueos@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    inicio = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )

    creado = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff_public_id,
            "starts_at": inicio.isoformat(),
            "ends_at": (inicio + timedelta(hours=2)).isoformat(),
            "reason": "Capacitación",
        },
    )
    assert creado.status_code in {200, 201}, creado.text
    block_id = cast(str, creado.json()["public_id"])

    listado = await client.get("/appointment-blocks/", headers=auth_headers(token))
    assert listado.status_code == 200
    assert any(b["public_id"] == block_id for b in listado.json())

    editado = await client.patch(
        f"/appointment-blocks/{block_id}",
        headers=auth_headers(token),
        json={"reason": "Capacitación interna"},
    )
    assert editado.status_code == 200, editado.text
    assert editado.json()["reason"] == "Capacitación interna"

    borrado = await client.delete(
        f"/appointment-blocks/{block_id}", headers=auth_headers(token)
    )
    assert borrado.status_code == 204, borrado.text


@pytest.mark.asyncio
async def test_un_bloqueo_invertido_se_rechaza(client: AsyncClient) -> None:
    """El fin no puede ser anterior al inicio."""
    _, token = await register_and_login(
        client, slug="bloqueo-invertido", email="bloqueo-inv@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    inicio = datetime.now(timezone.utc) + timedelta(days=2)

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff_public_id,
            "starts_at": inicio.isoformat(),
            "ends_at": (inicio - timedelta(hours=1)).isoformat(),
            "reason": "Invertido",
        },
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_un_bloqueo_impide_reservar_en_ese_horario(client: AsyncClient) -> None:
    """Interaccion real entre las dos agendas: bloqueo gana sobre turno nuevo."""
    _, token = await register_and_login(
        client, slug="bloqueo-choque", email="bloqueo-choque@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    dia = datetime.now(timezone.utc) + timedelta(days=2)
    await add_staff_schedule(client, token, staff_public_id, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)

    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
            "reason": "No atender",
        },
    )
    assert bloqueo.status_code in {200, 201}, bloqueo.text

    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "idempotency_key": "choque-con-bloqueo-0001",
        },
    )
    assert reserva.status_code >= 400, (
        f"se reservo sobre un bloqueo activo: {reserva.status_code}"
    )


@pytest.mark.asyncio
async def test_las_plantillas_de_bloqueo_estan_disponibles(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="bloqueo-plantillas", email="plantillas@test.com"
    )
    res = await client.get("/appointment-blocks/templates", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)
