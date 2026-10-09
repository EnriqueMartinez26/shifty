"""El resto del turno en la exportacion de datos y en la limpieza del seed.

Revision de la PR #137 (2026-10-08), saldo restante por turno (D-20261008-01):

- W3: ``GET /users/{client_id}/export`` (derecho de acceso, PV-05) traia los
  cobros del cliente pero no el resto que pago aparte: un pago suyo quedaba
  afuera de la exportacion. Ahora viaja en ``balance_payments``, vivo o
  revertido, como los cobros en ``payments``.
- ``scripts/seed_simulation.py::cleanup_seed`` borraba turnos y usuarios de
  las tiendas de simulacion sin borrar antes sus restos: en Postgres la FK
  del resto frenaba la limpieza.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import AppointmentStatus
from modules.payments.model import PaymentStatus
from scripts import seed_simulation as seed
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda


async def _turno_con_resto(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[str, str, str]:
    token, store, staff, servicio = await _tienda(client, session, slug)
    semilla = _Semilla(session, store, staff)
    ana = semilla.cliente("Ana", "Exporta")
    await session.commit()
    turno = await semilla.turno(
        f"{slug}-1",
        date(2026, 10, 8),
        time(10, 0),
        servicio,
        ana,
        AppointmentStatus.COMPLETED,
        precio=Decimal("3200"),
        pago=(Decimal("960"), PaymentStatus.APPROVED),
    )
    res = await client.post(
        f"/payments/{turno}/remaining-payment",
        headers=auth_headers(token),
        json={"idempotency_key": f"{slug}-resto-0001", "method": "efectivo"},
    )
    assert res.status_code == 201, res.text
    return token, turno, ana.public_id


@pytest.mark.asyncio
async def test_la_exportacion_del_cliente_trae_su_resto(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, turno, cliente = await _turno_con_resto(client, test_session, "exp-resto")

    res = await client.get(f"/users/{cliente}/export", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    (resto,) = res.json()["balance_payments"]
    assert resto["appointment_id"] == turno
    assert Decimal(resto["amount"]) == Decimal("2240")
    assert resto["method"] == "efectivo"
    assert resto["created_at"]
    assert resto["reverted_at"] is None


@pytest.mark.asyncio
async def test_la_limpieza_del_seed_borra_los_restos_de_sus_turnos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    slug = str(seed.STORE_SCENARIOS[0]["slug"])
    _, turno, _ = await _turno_con_resto(client, test_session, slug)
    # El seed marca sus turnos con este prefijo; la limpieza solo toca esos.
    await test_session.execute(
        text("update appointments set idempotency_key = :k where id = :t"),
        {"k": f"{seed.SIMULATION_CONTEXT_PREFIX}:turno-con-resto", "t": turno},
    )
    await test_session.commit()

    await seed.cleanup_seed(test_session)
    await test_session.commit()

    for tabla in ("appointment_balance_payments", "payments", "appointments"):
        quedan = await test_session.scalar(text(f"select count(*) from {tabla}"))
        assert quedan == 0, tabla
