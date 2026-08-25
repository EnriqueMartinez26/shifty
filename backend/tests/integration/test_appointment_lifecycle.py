"""Ciclo de vida del turno a traves de la capa de servicio.

Los tests de invariantes prueban el grafo sobre el modelo. Estos ejercitan la
orquestacion: los guards de rol, los locks, la auditoria y las transiciones
reales disparadas por los endpoints administrativos.
"""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditLog

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _book(
    client: AsyncClient, token: str, *, hour: int, key: str, days: int = 3
) -> tuple[str, str]:
    """Crea servicio, staff, agenda y reserva un turno. Devuelve (id, staff_id)."""
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=days)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=hour, minute=0, second=0, microsecond=0)

    res = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "idempotency_key": key,
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"]), staff_public_id


@pytest.mark.asyncio
async def test_camino_feliz_pendiente_confirmado_completado(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="ciclo-feliz", email="ciclo-feliz@test.com"
    )
    appointment_id, _ = await _book(client, token, hour=9, key="ciclo-feliz-0001")

    confirmado = await client.patch(
        f"/appointments/{appointment_id}/confirm", headers=auth_headers(token)
    )
    assert confirmado.status_code == 200, confirmado.text
    assert confirmado.json()["status"] == "confirmed"

    completado = await client.patch(
        f"/appointments/{appointment_id}/complete", headers=auth_headers(token)
    )
    assert completado.status_code == 200, completado.text
    assert completado.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_un_turno_completado_es_absorbente(client: AsyncClient) -> None:
    """La transicion ilegal se rechaza en la capa de servicio, no solo en el modelo."""
    _, token = await register_and_login(
        client, slug="ciclo-absorbente", email="absorbente@test.com"
    )
    appointment_id, _ = await _book(client, token, hour=10, key="absorbente-0001")

    await client.patch(
        f"/appointments/{appointment_id}/confirm", headers=auth_headers(token)
    )
    await client.patch(
        f"/appointments/{appointment_id}/complete", headers=auth_headers(token)
    )

    for accion in ("cancel", "absent", "confirm"):
        res = await client.patch(
            f"/appointments/{appointment_id}/{accion}", headers=auth_headers(token)
        )
        assert res.status_code >= 400, (
            f"{accion} sobre completado devolvio {res.status_code}"
        )


@pytest.mark.asyncio
async def test_marcar_ausente_requiere_turno_confirmado(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="ciclo-ausente", email="ausente@test.com"
    )
    appointment_id, _ = await _book(client, token, hour=11, key="ausente-0001")

    # pending -> absent no existe en el grafo.
    prematuro = await client.patch(
        f"/appointments/{appointment_id}/absent", headers=auth_headers(token)
    )
    assert prematuro.status_code >= 400, prematuro.text

    await client.patch(
        f"/appointments/{appointment_id}/confirm", headers=auth_headers(token)
    )
    ausente = await client.patch(
        f"/appointments/{appointment_id}/absent", headers=auth_headers(token)
    )
    assert ausente.status_code == 200, ausente.text
    assert ausente.json()["status"] == "absent"


@pytest.mark.asyncio
async def test_cancelar_un_turno_pendiente(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="ciclo-cancela", email="cancela@test.com"
    )
    appointment_id, _ = await _book(client, token, hour=12, key="cancela-0001")

    cancelado = await client.patch(
        f"/appointments/{appointment_id}/cancel", headers=auth_headers(token)
    )
    assert cancelado.status_code == 200, cancelado.text
    assert cancelado.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reprogramar_cancela_el_original_y_crea_uno_nuevo(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="ciclo-reagenda", email="ciclo-reagenda@test.com"
    )
    appointment_id, _ = await _book(client, token, hour=13, key="reagenda-0001")

    nuevo_horario = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    res = await client.patch(
        f"/appointments/{appointment_id}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": nuevo_horario.isoformat(),
            "idempotency_key": "reagenda-nuevo-0001",
        },
    )
    assert res.status_code == 200, res.text
    nuevo_id = res.json()["public_id"]
    assert nuevo_id != appointment_id

    original = await client.get(
        "/appointments/search",
        headers=auth_headers(token),
        params={"page": 1, "page_size": 50},
    )
    assert original.status_code == 200
    por_id = {row["public_id"]: row["status"] for row in original.json()["results"]}
    assert por_id[appointment_id] == "cancelled"
    assert por_id[nuevo_id] in {"pending", "confirmed"}


@pytest.mark.asyncio
async def test_transiciones_sobre_un_turno_inexistente_dan_404(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="ciclo-404", email="ciclo404@test.com"
    )
    for accion in ("confirm", "complete", "cancel", "absent"):
        res = await client.patch(
            f"/appointments/TURNOQUENOEXISTE/{accion}", headers=auth_headers(token)
        )
        assert res.status_code == 404, f"{accion}: {res.status_code}"


@pytest.mark.asyncio
async def test_cada_transicion_deja_rastro_de_auditoria(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La auditoria es parte de la transicion, no un agregado opcional."""
    _, token = await register_and_login(
        client, slug="ciclo-audit", email="ciclo-audit@test.com"
    )
    appointment_id, _ = await _book(client, token, hour=14, key="audit-0001")

    antes = await test_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.resource_id == appointment_id)
    )

    await client.patch(
        f"/appointments/{appointment_id}/confirm", headers=auth_headers(token)
    )
    await client.patch(
        f"/appointments/{appointment_id}/complete", headers=auth_headers(token)
    )

    despues = await test_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.resource_id == appointment_id)
    )
    assert (despues or 0) >= (antes or 0) + 2
