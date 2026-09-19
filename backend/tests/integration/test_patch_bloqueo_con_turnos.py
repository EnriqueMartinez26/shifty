"""Editar un bloqueo sobre turnos activos pide la misma confirmacion que el alta.

Auditoria 2, AUD2-B1-01 (2026-09-19). Sintoma: ``create_blocks`` lockea a los
profesionales, relee bajo lock los turnos que caen en el rango y exige
``cancel_affected``; ``PATCH /appointment-blocks/{id}`` no hacia nada de eso.
Agrandar un bloqueo de 13:00-14:00 a 13:00-16:00 (o moverlo, o reactivarlo)
dejaba adentro turnos activos: el recordatorio les seguia saliendo, el cliente
llegaba y el profesional no atendia. Ademas escribia ``appointment_blocks`` sin
el ``FOR UPDATE`` del profesional, asi que no se serializaba contra una reserva
en curso (regla 4).

Ahora el PATCH pasa por el mismo nucleo que el alta sobre los tramos que el
bloqueo empieza a cubrir (mover, agrandar, reactivar): lock, relectura bajo
lock, 409 ``BLOCK_HAS_APPOINTMENTS`` sin confirmacion y cancelacion con
auditoria y aviso por outbox con ``cancel_affected``. Achicar o desactivar no
cubre nada nuevo y no pide nada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


class Tienda(NamedTuple):
    store: str
    token: str
    staff: str
    service: str
    base: datetime
    slug: str


async def _tienda(client: AsyncClient, slug: str) -> Tienda:
    """Tienda con un profesional que atiende 06:00-18:00 local.

    ``base`` es las 13:00 UTC (10:00 local) de un dia futuro.
    """
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    return Tienda(store, token, staff, service, base, slug)


async def _reservar(client: AsyncClient, t: Tienda, cuando: datetime) -> str:
    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": cuando.isoformat(),
            "client_name": "Cliente Uno",
            "client_email": f"cliente-{t.slug}@example.com",
            "client_phone": "+5491155550123",
            "idempotency_key": f"patch-bloqueo-{t.slug}",
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _bloquear(
    client: AsyncClient, t: Tienda, inicio: datetime, fin: datetime
) -> str:
    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(t.token),
        json={
            "staff_id": t.staff,
            "starts_at": inicio.isoformat(),
            "ends_at": fin.isoformat(),
            "reason": "Tramite",
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _bloqueo(client: AsyncClient, t: Tienda, public_id: str) -> dict[str, Any]:
    res = await client.get("/appointment-blocks/", headers=auth_headers(t.token))
    assert res.status_code == 200, res.text
    [guardado] = [b for b in res.json() if b["public_id"] == public_id]
    return dict(guardado)


async def _estado(session: AsyncSession, public_id: str) -> str:
    session.expire_all()
    return str(
        (
            await session.execute(
                select(Appointment.status).where(Appointment.id == public_id)
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_agrandar_sobre_un_turno_activo_responde_409_y_no_escribe(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "patch-agranda")
    turno = await _reservar(client, t, t.base + timedelta(hours=2))
    bloqueo = await _bloquear(client, t, t.base, t.base + timedelta(hours=1))

    res = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={"ends_at": (t.base + timedelta(hours=3)).isoformat()},
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "BLOCK_HAS_APPOINTMENTS"
    assert res.json()["detail"]["affected"] == 1
    guardado = await _bloqueo(client, t, bloqueo)
    assert datetime.fromisoformat(guardado["ends_at"]) == t.base + timedelta(hours=1)
    assert await _estado(test_session, turno) != "cancelled"


@pytest.mark.asyncio
async def test_agrandar_sobre_agenda_libre_no_pide_confirmacion(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "patch-libre")
    await _reservar(client, t, t.base + timedelta(hours=4))
    bloqueo = await _bloquear(client, t, t.base, t.base + timedelta(hours=1))

    res = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={"ends_at": (t.base + timedelta(hours=2)).isoformat()},
    )

    assert res.status_code == 200, res.text
    assert datetime.fromisoformat(res.json()["ends_at"]) == t.base + timedelta(hours=2)


@pytest.mark.asyncio
async def test_mover_el_bloqueo_encima_de_un_turno_responde_409(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "patch-mueve")
    await _reservar(client, t, t.base + timedelta(hours=2))
    bloqueo = await _bloquear(client, t, t.base, t.base + timedelta(hours=1))

    encima = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={
            "starts_at": (t.base + timedelta(hours=2)).isoformat(),
            "ends_at": (t.base + timedelta(hours=3)).isoformat(),
        },
    )
    assert encima.status_code == 409, encima.text
    assert encima.json()["error_code"] == "BLOCK_HAS_APPOINTMENTS"

    # El mismo movimiento a un tramo sin turnos sigue siendo un PATCH comun.
    libre = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={
            "starts_at": (t.base + timedelta(hours=5)).isoformat(),
            "ends_at": (t.base + timedelta(hours=6)).isoformat(),
        },
    )
    assert libre.status_code == 200, libre.text


@pytest.mark.asyncio
async def test_reactivar_un_bloqueo_sobre_un_turno_responde_409(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "patch-reactiva")
    bloqueo = await _bloquear(
        client, t, t.base + timedelta(hours=2), t.base + timedelta(hours=3)
    )
    apagado = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={"is_active": False},
    )
    assert apagado.status_code == 200, apagado.text
    # Con el bloqueo apagado el horario vuelve a estar a la venta.
    await _reservar(client, t, t.base + timedelta(hours=2))

    res = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={"is_active": True},
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "BLOCK_HAS_APPOINTMENTS"
    assert (await _bloqueo(client, t, bloqueo))["is_active"] is False


@pytest.mark.asyncio
async def test_achicar_o_desactivar_no_pide_confirmacion(client: AsyncClient) -> None:
    t = await _tienda(client, "patch-achica")
    await _reservar(client, t, t.base + timedelta(hours=2))
    bloqueo = await _bloquear(client, t, t.base, t.base + timedelta(hours=1))

    achicado = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={"ends_at": (t.base + timedelta(minutes=30)).isoformat()},
    )
    assert achicado.status_code == 200, achicado.text

    borrado = await client.delete(
        f"/appointment-blocks/{bloqueo}", headers=auth_headers(t.token)
    )
    assert borrado.status_code == 204, borrado.text


@pytest.mark.asyncio
async def test_confirmar_cancela_los_turnos_de_adentro_y_avisa_por_outbox(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "patch-confirma")
    turno = await _reservar(client, t, t.base + timedelta(hours=2))
    bloqueo = await _bloquear(client, t, t.base, t.base + timedelta(hours=1))

    res = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={
            "ends_at": (t.base + timedelta(hours=3)).isoformat(),
            "cancel_affected": True,
        },
    )

    assert res.status_code == 200, res.text
    assert datetime.fromisoformat(res.json()["ends_at"]) == t.base + timedelta(hours=3)
    assert await _estado(test_session, turno) == "cancelled"
    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == "appointment.cancelled_by_block"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1


@pytest.mark.asyncio
async def test_el_patch_lockea_al_profesional_antes_de_decidir(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En SQLite no hay locks de fila: se verifica la sentencia (como S-11)."""
    t = await _tienda(client, "patch-lock")
    bloqueo = await _bloquear(client, t, t.base, t.base + timedelta(hours=1))

    locks: list[str] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        sql = str(statement)
        if "FROM staff" in sql and "FOR UPDATE" in sql:
            locks.append(sql)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    res = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(t.token),
        json={"ends_at": (t.base + timedelta(hours=2)).isoformat()},
    )
    monkeypatch.undo()

    assert res.status_code == 200, res.text
    assert len(locks) == 1, locks
    assert "ORDER BY staff.id" in locks[0], locks[0]
