"""El fiado solo se asocia a turnos de la propia tienda.

2026-09-20, hallazgo AUD2-B2-16: ``LedgerMovementCreate.appointment_id``
aceptaba cualquier string de hasta 64 caracteres, sin ``pattern`` y sin
comprobar que el turno fuera de la tienda; ``add_movement`` lo persistia tal
cual. La FK a ``appointments.id`` no pasa por RLS (Postgres verifica las
restricciones por fuera de las politicas), asi que una fila de fiado podia
quedar apuntando al turno de OTRA tienda. B2-11 cerro la mitad del hueco
(``client_id`` via ``_ensure_store_client``) y dejo esta. CLAUDE.md §2 pide el
filtro ``store_id`` como defensa en profundidad junto a la RLS, no en su lugar.

Sintoma: el alta respondia 200 con un ``appointment_id`` de otra tienda (o
inexistente, hasta que la FK lo rechazaba con 409 generico) y con un id que ni
tenia forma de id; ahora 404 para el ajeno y el inexistente, 422 para el
malformado, y 200 solo con un turno propio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.ledger.model import CustomerLedger
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _habilitar_fiado(client: AsyncClient, token: str) -> None:
    res = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert res.status_code == 200, res.text


async def _reserva(
    client: AsyncClient, token: str, store: str, *, clave: str
) -> tuple[str, str]:
    """Reserva publica en la tienda: devuelve (client_id, appointment_id)."""
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{clave}@test.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=15, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": f"Cliente {clave}",
            "client_phone": f"+54911000{len(clave):04d}{ord(clave[-1]):03d}",
            "accepts_terms": True,
            "idempotency_key": f"fiado-turno-{clave}",
        },
    )
    assert booking.status_code == 201, booking.text
    turno = cast(str, booking.json()["public_id"])
    search = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    assert search.status_code == 200, search.text
    cliente = next(
        item for item in search.json()["results"] if item["public_id"] == turno
    )["client_id"]
    return cast(str, cliente), turno


async def _cargar(
    client: AsyncClient, token: str, cliente: str, appointment_id: str
) -> int:
    res = await client.post(
        f"/ledger/customers/{cliente}/movements",
        headers=auth_headers(token),
        json={
            "movement_type": "charge",
            "amount": "100.00",
            "appointment_id": appointment_id,
        },
    )
    return res.status_code


@pytest.mark.asyncio
async def test_no_se_carga_fiado_contra_un_turno_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda_a, token_a = await register_and_login(
        client, slug="fiado-turno-a", email="fiado-turno-a@test.com"
    )
    tienda_b, token_b = await register_and_login(
        client, slug="fiado-turno-b", email="fiado-turno-b@test.com"
    )
    await _habilitar_fiado(client, token_a)
    cliente_a, turno_a = await _reserva(client, token_a, tienda_a, clave="ta")
    _cliente_b, turno_b = await _reserva(client, token_b, tienda_b, clave="tb")

    # Cliente propio, turno ajeno: la fila no se carga.
    assert await _cargar(client, token_a, cliente_a, turno_b) == 404
    # Turno con forma de id pero inexistente: 404 explicito, no 409 por FK.
    assert await _cargar(client, token_a, cliente_a, "01J000000000000000000NADA") == 404
    # Sin forma de id: lo frena el schema antes de tocar la base.
    assert await _cargar(client, token_a, cliente_a, "no es un id!") == 422

    filas = await test_session.scalar(select(func.count()).select_from(CustomerLedger))
    assert filas == 0

    # Guarda viva: el turno propio sigue asociandose al movimiento.
    propio = await client.post(
        f"/ledger/customers/{cliente_a}/movements",
        headers=auth_headers(token_a),
        json={
            "movement_type": "charge",
            "amount": "100.00",
            "appointment_id": turno_a,
        },
    )
    assert propio.status_code == 200, propio.text
    assert propio.json()["appointment_id"] == turno_a
