"""Sena por WhatsApp contra Postgres: confirmar a mano contra vencer la retencion.

Decision de Mateo (2026-10-03): una sena obligatoria se paga por Mercado Pago
o por WhatsApp; por WhatsApp el turno nace ``pending_payment`` con un cobro
``pending`` de proveedor ``manual`` y el personal lo confirma a mano desde el
panel (``POST /payments/{turno}/manual-confirm``), sin MP ni el flag
``payments``. Si nadie lo confirma, el job de retenciones vencidas lo vence
por el grafo.

Lo que SQLite no puede probar (CLAUDE.md §4): las dos cosas a la vez, con una
sesion por request. Los dos caminos toman primero el TURNO (regla 7: la
confirmacion con ``lock_payable_appointment``, ``FOR UPDATE``; el job con
``FOR UPDATE SKIP LOCKED`` sobre el turno) y despues escriben el pago, asi que
se serializan sobre la fila del turno, sin deadlock y sin estados mezclados:

- gana la confirmacion: turno ``confirmed``, cobro ``manual_confirmed``, un
  ``appointment.confirmed`` en el outbox y el job no lo toca;
- gana el job: turno y cobro ``expired``, el cupo liberado y la confirmacion
  responde 409 ``APPOINTMENT_NOT_PAYABLE`` (regla 3: un turno soltado no se
  cobra).

Nunca un turno vencido con el cobro confirmado ni al reves, y cero 5xx.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.jobs import expire_unpaid_appointments
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.test_pg_lotes_skip_locked import _con_bypass

pytestmark = pytest.mark.postgres

TURNOS = 3
RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


@dataclass(frozen=True)
class _Tienda:
    token: str
    turnos: list[str]


def _mp_prohibido(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    llamadas: list[str] = []

    async def prohibido(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append(path)
        raise AssertionError(f"una sena por WhatsApp no consulta a MP: {path}")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", prohibido)
    return llamadas


async def _tienda_con_senas_por_whatsapp(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    slug: str,
    cuantos: int,
) -> _Tienda:
    """Tienda SIN Mercado Pago ni flag ``payments``, con WhatsApp, y
    ``cuantos`` turnos con la sena del 30 % pendiente por WhatsApp."""
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    canal = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"whatsapp_number": "11 5555 0303"},
    )
    assert canal.status_code == 200, canal.text
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    turnos: list[str] = []
    for i in range(cuantos):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": servicio,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911566{i:05d}",
                "payment_method": "manual",
                "accepts_terms": True,
                "idempotency_key": f"{slug}-{i:06d}",
            },
        )
        assert reserva.status_code == 201, reserva.text
        assert reserva.json()["status"] == "pending_payment", reserva.text
        turnos.append(str(reserva.json()["public_id"]))
    return _Tienda(token, turnos)


async def _vencer_retenciones(owner_engine: AsyncEngine, turnos: list[str]) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update appointments set expires_at = :t where id = any(:ids)"),
            {"t": datetime.now(timezone.utc) - timedelta(minutes=1), "ids": turnos},
        )


async def _estado(owner_engine: AsyncEngine, turno: str) -> tuple[str, str, str]:
    async with owner_engine.connect() as conn:
        fila = (
            await conn.execute(
                text(
                    "select a.status, p.status, p.provider from appointments a "
                    "join payments p on p.appointment_id = a.id where a.id = :id"
                ),
                {"id": turno},
            )
        ).one()
    return str(fila[0]), str(fila[1]), str(fila[2])


async def _eventos(owner_engine: AsyncEngine, tipo: str, turno: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from outbox_messages where event_type = :tipo "
                    "and payload->>'appointment_id' = :turno"
                ),
                {"tipo": tipo, "turno": turno},
            )
        ).scalar_one()
    return int(total)


def _confirmar(client: AsyncClient, token: str, turno: str) -> Any:
    return client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={"notes": "transferencia por WhatsApp"},
    )


@pytest.mark.asyncio
async def test_confirmar_a_mano_y_vencer_la_retencion_a_la_vez_no_mezclan_estados(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas = _mp_prohibido(monkeypatch)
    t = await _tienda_con_senas_por_whatsapp(
        client, app_sessions, "pg-wa-carrera", TURNOS
    )
    await _vencer_retenciones(owner_engine, t.turnos)

    async def vencer(db: AsyncSession) -> dict[str, int]:
        return await expire_unpaid_appointments(db, limit=TURNOS)

    resultados = await asyncio.gather(
        *(_confirmar(client, t.token, turno) for turno in t.turnos),
        _con_bypass(app_sessions, vencer),
    )
    respuestas: list[Response] = list(resultados[:-1])
    corrida = resultados[-1]

    assert all(r.status_code < 500 for r in respuestas), [r.text for r in respuestas]
    assert llamadas == []
    vencidos = 0
    for turno, respuesta in zip(t.turnos, respuestas, strict=True):
        turno_estado, cobro_estado, proveedor = await _estado(owner_engine, turno)
        assert proveedor == "manual"
        confirmados = await _eventos(owner_engine, "appointment.confirmed", turno)
        liberados = await _eventos(owner_engine, "appointment.slot_released", turno)
        if respuesta.status_code == 200:
            assert (turno_estado, cobro_estado) == ("confirmed", "manual_confirmed")
            assert (confirmados, liberados) == (1, 0)
        else:
            assert respuesta.status_code == 409, respuesta.text
            assert respuesta.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"
            assert (turno_estado, cobro_estado) == ("expired", "expired")
            assert (confirmados, liberados) == (0, 1)
            vencidos += 1
    assert isinstance(corrida, dict)
    assert corrida["expired"] == vencidos, corrida
    assert corrida["held"] == 0, corrida


@pytest.mark.asyncio
async def test_el_job_saltea_la_sena_que_se_esta_confirmando(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orden fijo: con el turno lockeado (como lo deja la confirmacion antes
    de escribir el pago), el job lo saltea con SKIP LOCKED en vez de vencerlo
    o de esperar; al soltarse el lock la confirmacion termina."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mp_prohibido(monkeypatch)
    t = await _tienda_con_senas_por_whatsapp(client, app_sessions, "pg-wa-lock", 1)
    (turno,) = t.turnos
    await _vencer_retenciones(owner_engine, t.turnos)

    async def vencer(db: AsyncSession) -> dict[str, int]:
        return await expire_unpaid_appointments(db, limit=TURNOS)

    async with owner_engine.connect() as conn:
        transaccion = await conn.begin()
        await conn.execute(
            text("select id from appointments where id = :id for update"),
            {"id": turno},
        )
        confirmacion = asyncio.create_task(_confirmar(client, t.token, turno))
        await asyncio.sleep(0.3)  # la confirmacion queda esperando el lock
        corrida = await _con_bypass(app_sessions, vencer)
        await transaccion.rollback()
    respuesta = await confirmacion

    assert corrida["expired"] == 0, corrida
    assert respuesta.status_code == 200, respuesta.text
    assert await _estado(owner_engine, turno) == (
        "confirmed",
        "manual_confirmed",
        "manual",
    )


@pytest.mark.asyncio
async def test_rafaga_de_confirmaciones_de_una_sena_por_whatsapp_sin_flag(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N confirmaciones a la vez del mismo turno con los cobros APAGADOS:
    cero 5xx, una sola transicion y un solo mail de "turno confirmado"."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas = _mp_prohibido(monkeypatch)
    t = await _tienda_con_senas_por_whatsapp(client, app_sessions, "pg-wa-rafaga", 1)
    (turno,) = t.turnos

    respuestas = await asyncio.gather(
        *(_confirmar(client, t.token, turno) for _ in range(RAFAGA))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert 200 in codigos, codigos
    assert set(codigos) <= {200, 409}, codigos
    assert await _estado(owner_engine, turno) == (
        "confirmed",
        "manual_confirmed",
        "manual",
    )
    assert await _eventos(owner_engine, "appointment.confirmed", turno) == 1
    assert llamadas == []
