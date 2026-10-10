"""Ascender a SuperAdmin saca de la agenda publica la ficha de la cuenta.

2026-10-10 (seguimiento de #133). Sintoma: un admin de tienda que se agrego
como profesional (``POST /staff/me``) y despues fue ascendido a SuperAdmin
(``PATCH /superadmin/users/{id}/global-admin``) seguia reservable en el
portal publico, mientras el panel de su tienda lo escondia
(``_visible_para_el_panel``, S-15): ningun admin de la tienda lo veia ni lo
podia quitar. ``set_global_admin`` no tocaba la ficha.

La cuenta global no atiende en ninguna tienda (``add_self`` ya lo niega con
``STAFF_SELF_GLOBAL_ADMIN_DENIED``). Al ascender, la ficha pasa a inactiva en
la MISMA transaccion: no se borra, conserva su historia (turnos, horarios,
servicios). Revocar el flag NO la reactiva: volver a la agenda es una
decision de la cuenta (``POST /staff/me`` reactiva la misma ficha).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ARGENTINA_TZ
from modules.staff.model import Staff
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)

PASSWORD = "Password123!"
DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


async def _cuenta(session: AsyncSession, email: str) -> User:
    return (
        await session.execute(
            select(User)
            .where(User.email == email)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _ficha(session: AsyncSession, staff_id: str) -> Staff:
    return (
        await session.execute(
            select(Staff)
            .where(Staff.id == staff_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _superadmin_de_otra_tienda(
    client: AsyncClient, session: AsyncSession, slug: str
) -> dict[str, str]:
    email = f"{slug}@t.com"
    await register_and_login(client, slug=slug, email=email)
    cuenta = await _cuenta(session, email)
    cuenta.is_global_admin = True
    await session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return auth_headers(str(login.json()["access_token"]))


async def _staff_publico(client: AsyncClient, store: str, service: str) -> set[str]:
    res = await client.get(
        "/public/staff", params={"store_public_id": store, "service_id": service}
    )
    assert res.status_code == 200, res.text
    return {s["public_id"] for s in res.json()}


async def _slots_de(
    client: AsyncClient, store: str, service: str, dia: str, staff_id: str
) -> list[dict[str, str]]:
    res = await client.get(
        "/public/availability",
        params={"store_public_id": store, "service_id": service, "date": dia},
    )
    assert res.status_code == 200, res.text
    return [
        s
        for s in res.json()
        if s["staff_id"] == staff_id and s["status"] == "available"
    ]


async def _duenio_que_atiende(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[str, str, str, str, str]:
    """Tienda con su dueno agregado como profesional y horario abierto.

    Devuelve (store, service, staff_id, dia local, token del dueno).
    """
    email = f"{slug}@t.com"
    store, token = await register_and_login(client, slug=slug, email=email)
    service = await create_service(client, token)
    alta = await client.post(
        "/staff/me", headers=auth_headers(token), json={"service_ids": [service]}
    )
    assert alta.status_code == 201, alta.text
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    local = dia.astimezone(ARGENTINA_TZ).date()
    horario = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "business_hours": {
                DIAS[local.weekday()]: [{"open": "09:00", "close": "18:00"}]
            }
        },
    )
    assert horario.status_code == 200, horario.text
    return store, service, str(alta.json()["public_id"]), local.isoformat(), token


@pytest.mark.asyncio
async def test_ascender_a_superadmin_lo_saca_del_portal(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, service, staff_id, dia, _ = await _duenio_que_atiende(
        client, test_session, "asc-portal"
    )
    sa = await _superadmin_de_otra_tienda(client, test_session, "asc-portal-sa")
    # Antes de ascender figura y tiene turnos (y la disponibilidad queda en el
    # cache: el ascenso tiene que invalidarla).
    assert staff_id in await _staff_publico(client, store, service)
    assert await _slots_de(client, store, service, dia, staff_id)

    res = await client.patch(
        f"/superadmin/users/{staff_id}/global-admin",
        headers=sa,
        json={"is_global_admin": True},
    )

    assert res.status_code == 200, res.text
    assert staff_id not in await _staff_publico(client, store, service)
    assert await _slots_de(client, store, service, dia, staff_id) == []
    # La ficha no se borra: queda inactiva, con su historia.
    ficha = await _ficha(test_session, staff_id)
    assert ficha.is_active is False


@pytest.mark.asyncio
async def test_el_portal_no_reserva_con_el_ascendido(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, service, staff_id, dia, _ = await _duenio_que_atiende(
        client, test_session, "asc-reserva"
    )
    sa = await _superadmin_de_otra_tienda(client, test_session, "asc-reserva-sa")
    slot = (await _slots_de(client, store, service, dia, staff_id))[0]
    ascenso = await client.patch(
        f"/superadmin/users/{staff_id}/global-admin",
        headers=sa,
        json={"is_global_admin": True},
    )
    assert ascenso.status_code == 200, ascenso.text

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff_id,
            "starts_at": slot["starts_at"],
            "client_name": "Cliente",
            "client_phone": "+5491155550199",
            "accepts_terms": True,
            "idempotency_key": "asc-reserva-1",
        },
    )

    assert reserva.status_code != 201, reserva.text
    assert 400 <= reserva.status_code < 500, reserva.text


@pytest.mark.asyncio
async def test_revocar_el_flag_no_lo_vuelve_a_la_agenda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, service, staff_id, _, _ = await _duenio_que_atiende(
        client, test_session, "asc-revoca"
    )
    sa = await _superadmin_de_otra_tienda(client, test_session, "asc-revoca-sa")
    for habilitar in (True, False):
        res = await client.patch(
            f"/superadmin/users/{staff_id}/global-admin",
            headers=sa,
            json={"is_global_admin": habilitar},
        )
        assert res.status_code == 200, (habilitar, res.text)

    assert (await _ficha(test_session, staff_id)).is_active is False
    assert staff_id not in await _staff_publico(client, store, service)
