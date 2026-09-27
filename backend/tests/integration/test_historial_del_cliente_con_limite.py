"""El historial publico del cliente tiene tope y se lee en una consulta.

F3-09 (plan de rendimiento, R1-09, 2026-09-24). Sintoma: ``GET
/public/client/{tienda}/{telefono}/appointments`` devolvia la historia
COMPLETA del cliente, sin limite, y por cada request cargaba servicio y
profesional con ``selectinload``; el profesional arrastraba en cascada sus
``services`` y ``schedules`` (``lazy="selectin"``), dos consultas mas que la
respuesta no usa. Y la tienda se cargaba entera (con sus horarios) para leer
dos columnas.

Ahora ``limit`` (aditivo: default 50, ``ge=1`` y ``le=200``, regla 9) acota
la lista, los mas recientes primero como siempre, y turnos + servicio +
profesional salen en un solo SELECT con JOIN sin cascadas.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.appointments.model import Appointment
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno

EXTRAS = 55


async def _con_historia(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> str:
    t, turno_id = await _con_turno(client, monkeypatch, slug)
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == turno_id)
        )
    ).scalar_one()
    # Historia vieja del mismo cliente: un turno completado por semana hacia atras.
    for semana in range(1, EXTRAS + 1):
        inicio = turno.starts_at - timedelta(weeks=semana)
        test_session.add(
            Appointment(
                store_id=turno.store_id,
                staff_id=turno.staff_id,
                service_id=turno.service_id,
                client_id=turno.client_id,
                client_name=turno.client_name,
                client_phone=turno.client_phone,
                starts_at=inicio,
                ends_at=inicio + timedelta(minutes=30),
                duration_minutes=30,
                status="completed",
                idempotency_key=f"{slug}-historia-{semana:03d}",
            )
        )
    await test_session.commit()
    return t.store


def _url(store: str) -> str:
    return f"/public/client/{store}/{TELEFONO}/appointments"


@pytest.mark.asyncio
async def test_por_defecto_devuelve_los_50_mas_recientes(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await _con_historia(client, test_session, monkeypatch, "historial-def")

    res = await client.get(_url(store))

    assert res.status_code == 200, res.text
    turnos = res.json()["appointments"]
    assert len(turnos) == 50
    inicios = [t["starts_at"] for t in turnos]
    assert inicios == sorted(inicios, reverse=True), "mas recientes primero"
    # El primero es el turno futuro (el alta), que sigue autogestionable.
    assert turnos[0]["status"] == "pending"
    assert turnos[0]["can_cancel"] is True
    assert {t["service_name"] for t in turnos} == {"Consulta"}
    assert {t["staff_name"] for t in turnos} == {"Pro Demo"}


@pytest.mark.asyncio
async def test_limit_acota_y_respeta_el_orden(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await _con_historia(client, test_session, monkeypatch, "historial-lim")

    completo = await client.get(_url(store), params={"limit": 200})
    tres = await client.get(_url(store), params={"limit": 3})

    assert completo.status_code == 200, completo.text
    assert tres.status_code == 200, tres.text
    assert len(completo.json()["appointments"]) == EXTRAS + 1
    assert tres.json()["appointments"] == completo.json()["appointments"][:3]


@pytest.mark.asyncio
@pytest.mark.parametrize("limite", [0, 201, -1])
async def test_limit_fuera_de_rango_es_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, limite: int
) -> None:
    t, _turno = await _con_turno(client, monkeypatch, f"historial-422-{limite + 1}")

    res = await client.get(_url(t.store), params={"limit": limite})

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_turnos_servicio_y_profesional_en_una_consulta_sin_cascadas(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = await _con_historia(client, test_session, monkeypatch, "historial-sql")
    # Sesion "fresca", como la de un request real: sin esto el identity map
    # del test ya tiene tienda y profesional cargados y no se ve la cascada.
    test_session.expunge_all()

    sentencias: list[str] = []

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.split()).lower())

    event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
    try:
        res = await client.get(_url(store))
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)

    assert res.status_code == 200, res.text
    cascadas = [
        s
        for s in sentencias
        if "staff_services" in s or "from schedules" in s or "from store_schedules" in s
    ]
    assert cascadas == [], cascadas
    assert not [s for s in sentencias if s.startswith("select services.")], (
        "el servicio viene en el JOIN de los turnos"
    )
    # Antes 10 (tienda + sus horarios, OTP x2, cliente, turnos, servicio,
    # profesional + sus horarios y servicios). Ahora: tienda (2 columnas) +
    # OTP (ficha + verificacion) + cliente + turnos con JOIN.
    assert len(sentencias) <= 5, sentencias
    assert len(res.json()["appointments"]) == 50
