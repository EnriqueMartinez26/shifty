"""Reprogramar toma el lock del profesional ANTES de leer los bloqueos.

Audit B1-05 (2026-09-17), regla 4 de CLAUDE.md. Sintoma: ``book`` y el alta
publica ya tomaban ``FOR UPDATE`` sobre el profesional antes de consultar
``appointment_blocks`` (carrera reproducida en tests/postgres/test_pg_bloqueos
.py), pero ``AppointmentService.reschedule`` y ``client_reschedule_appointment``
leian los bloqueos primero y recien despues tomaban el lock: entre esa lectura
y el INSERT un bloqueo recien creado dejaba el turno nuevo adentro. La
exclusion GiST no lo cubre (turnos contra turnos, no contra bloqueos).

SQLite no tiene locks de fila, asi que este test no reproduce la carrera:
verifica el ORDEN de las sentencias que salen por la sesion. La carrera de
verdad esta en tests/postgres/test_pg_bloqueos.py.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


def _espiar_orden_de_sentencias(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Registra, en orden, el FOR UPDATE sobre staff y las lecturas de bloqueos."""
    registro: list[str] = []
    original = session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        obtener_froms = getattr(statement, "get_final_froms", None)
        tablas = (
            {getattr(f, "name", None) for f in obtener_froms()}
            if obtener_froms
            else set()
        )
        if (
            "staff" in tablas
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            registro.append("lock_staff")
        elif "appointment_blocks" in tablas:
            registro.append("leer_bloqueos")
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute_espiado)
    return registro


def _assert_lock_antes_de_bloqueos(registro: list[str]) -> None:
    assert "leer_bloqueos" in registro, registro
    assert "lock_staff" in registro, registro
    assert registro.index("lock_staff") < registro.index("leer_bloqueos"), registro


async def _tienda_con_turno(
    client: AsyncClient, slug: str, phone: str
) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "client_name": "Orden",
            # La autogestion exige una ficha con email ENTREGABLE verificado por
            # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
            "client_email": "orden@example.com",
            "client_phone": phone,
            "idempotency_key": f"{slug}-original",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return store, token, reserva.json()["public_id"], base


@pytest.mark.asyncio
async def test_reprogramar_desde_el_panel_toma_el_lock_antes_de_leer_bloqueos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token, turno, base = await _tienda_con_turno(
        client, "orden-panel", "+5491155550501"
    )
    registro = _espiar_orden_de_sentencias(test_session, monkeypatch)

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": (base + timedelta(hours=2)).isoformat(),
            "idempotency_key": "orden-panel-reprogramar-1",
        },
    )
    assert res.status_code == 200, res.text
    _assert_lock_antes_de_bloqueos(registro)


@pytest.mark.asyncio
async def test_reprogramar_desde_el_cliente_toma_el_lock_antes_de_leer_bloqueos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    telefono = "+5491155550502"
    store, _token, turno, base = await _tienda_con_turno(
        client, "orden-cliente", telefono
    )
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": telefono, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": telefono,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text
    registro = _espiar_orden_de_sentencias(test_session, monkeypatch)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": telefono,
            "new_starts_at": (base + timedelta(hours=2)).isoformat(),
            "idempotency_key": "orden-cliente-reprogramar-1",
        },
    )
    assert res.status_code == 200, res.text
    _assert_lock_antes_de_bloqueos(registro)
