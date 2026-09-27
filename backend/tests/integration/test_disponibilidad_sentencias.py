"""Cuanto le cuesta a la base la disponibilidad publica (F3-02).

Plan de rendimiento, R1-01/R1-02 (2026-09-24). ``GET /public/availability``
es el endpoint mas pedido del portal. Sintomas:

- Con el cache CALIENTE (HIT) igual iba a la base: resolvia la tienda con
  ``select(Store)``, que trae en cascada sus horarios comerciales
  (``lazy="selectin"``), dos sentencias para usar solo el id.
- Con el cache FRIO (MISS) eran ~12 sentencias: el servicio, TODOS los
  profesionales de la tienda con sus servicios y sus horarios en cascada, la
  tienda de nuevo, los horarios del dia, los turnos con su servicio en JOIN y
  los bloqueos.
- La clave es por servicio: con N servicios, el mismo dia de la misma tienda
  se recalculaba N veces desde la base aunque la agenda fuera la misma.

Ahora: HIT = 1 sentencia (id y reglas de la tienda en columnas); MISS <= 6
(tienda, servicio con sus profesionales en un JOIN sobre ``staff_services``,
horarios, turnos y bloqueos del dia en columnas); y un segundo nivel de cache,
la "agenda cruda" del dia (ocupados, bloqueos, horarios y reglas de la
tienda) por (tienda, dia local), bajo la MISMA generacion + version que los
slots: el 2do..N-esimo servicio del mismo dia cuesta <= 2 sentencias y toda
invalidacion existente (reservar, cancelar, bloquear, editar un servicio) la
cubre por construccion.

SQLite no ejecuta los ``set_config`` del contexto de tienda
(``_apply_tenant_context`` sale antes por dialecto): en Postgres se suman los
dos del ``tenant_bypass`` a cada cuenta de aca.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import core.utils
import modules.notifications.tasks as tasks
from core.redis import get_availability_cache
from core.utils import local_to_utc
from main import app
from tests.conftest import MockRedis
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


def _local(dia: date, hhmm: str) -> datetime:
    hora, minuto = (int(p) for p in hhmm.split(":"))
    return local_to_utc(dia, time(hora, minuto))


@contextmanager
def _sentencias(engine: AsyncEngine) -> Iterator[list[str]]:
    registradas: list[str] = []

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        registradas.append(" ".join(statement.split()).lower())

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        yield registradas
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)


class _Tienda:
    def __init__(
        self,
        store: str,
        token: str,
        servicios: list[str],
        ana: str,
        beto: str,
        turno: str,
        dia: date,
    ) -> None:
        self.store = store
        self.token = token
        self.servicios = servicios
        self.ana = ana
        self.beto = beto
        self.turno = turno
        self.dia = dia


async def _servicio(client: AsyncClient, token: str, nombre: str, minutos: int) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": minutos, "price": 1000},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _profesional(
    client: AsyncClient, token: str, nombre: str, servicios: list[str], dia: date
) -> str:
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": nombre,
            "first_name": nombre,
            "last_name": "Test",
            "email": f"{nombre.lower()}@sentencias.com",
            "service_ids": servicios,
        },
    )
    assert res.status_code == 201, res.text
    staff = str(res.json()["public_id"])
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "09:00:00",
            "end_time": "13:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    return staff


async def _tienda(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, slug: str
) -> _Tienda:
    """Tres servicios; Ana hace los tres y Beto solo el primero.

    Ana tiene un turno a las 10:00 y Beto un bloqueo de 11:00 a 12:00.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    ajuste = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 15}
    )
    assert ajuste.status_code == 200, ajuste.text
    servicios = [
        await _servicio(client, token, "Corte", 30),
        await _servicio(client, token, "Color", 45),
        await _servicio(client, token, "Peinado", 60),
    ]
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    ana = await _profesional(client, token, "Ana", servicios, dia)
    beto = await _profesional(client, token, "Beto", servicios[:1], dia)
    turno = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicios[0],
            "staff_id": ana,
            "starts_at": _local(dia, "10:00").isoformat(),
            "idempotency_key": f"{slug}-turno-01",
        },
    )
    assert turno.status_code == 201, turno.text
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": beto,
            "starts_at": _local(dia, "11:00").isoformat(),
            "ends_at": _local(dia, "12:00").isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    # "Ahora" = 07:15 local del dia: la antelacion (2 h) corta a las 09:15.
    congelado = _local(dia, "07:15")
    monkeypatch.setattr(core.utils, "now_utc", lambda: congelado)
    return _Tienda(
        store, token, servicios, ana, beto, str(turno.json()["public_id"]), dia
    )


async def _disponibilidad(client: AsyncClient, t: _Tienda, servicio: str) -> Any:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": t.store,
            "service_id": servicio,
            "date": t.dia.isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _cache_nuevo() -> MockRedis:
    """Un Redis de cache vacio: lo que calcula la base sin ningun nivel."""
    nuevo = MockRedis()

    async def fake() -> MockRedis:
        return nuevo

    app.dependency_overrides[get_availability_cache] = fake
    return nuevo


def _lee_la_agenda(sentencias: list[str]) -> bool:
    return any("from appointments" in s for s in sentencias)


@pytest.mark.asyncio
async def test_hit_solo_resuelve_la_tienda_en_columnas(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tienda(client, monkeypatch, "sentencias-hit")
    primera = await _disponibilidad(client, t, t.servicios[0])
    # Sesion "fresca", como la de un request real (el identity map del test ya
    # tiene la tienda y sus horarios cargados y esconderia la cascada).
    test_session.expunge_all()

    with _sentencias(test_engine) as sentencias:
        segunda = await _disponibilidad(client, t, t.servicios[0])

    assert segunda == primera
    # Antes: 2 (tienda + sus horarios comerciales en cascada).
    assert len(sentencias) == 1, sentencias
    assert "from stores" in sentencias[0]
    assert "store_schedules" not in sentencias[0]


@pytest.mark.asyncio
async def test_miss_en_seis_sentencias_o_menos(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tienda(client, monkeypatch, "sentencias-miss")
    _cache_nuevo()
    test_session.expunge_all()

    with _sentencias(test_engine) as sentencias:
        slots = await _disponibilidad(client, t, t.servicios[0])

    assert {s["staff_id"] for s in slots} == {t.ana, t.beto}
    assert len(sentencias) <= 6, sentencias
    # Las cargas en cascada (``lazy="selectin"``) de la tienda y de los
    # profesionales: sus horarios y sus servicios (``staff AS staff_1``).
    cascadas = [
        s
        for s in sentencias
        if "store_schedules" in s
        or "staff_1" in s
        or "where schedules.staff_id in" in s
    ]
    assert cascadas == [], cascadas
    turnos = [s for s in sentencias if "from appointments" in s]
    assert len(turnos) == 1, turnos
    assert "services." not in turnos[0], "los turnos no traen su servicio"


@pytest.mark.asyncio
async def test_otro_servicio_del_mismo_dia_sale_de_la_agenda_cacheada(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tienda(client, monkeypatch, "sentencias-agenda")
    await _disponibilidad(client, t, t.servicios[0])
    test_session.expunge_all()

    derivados: list[Any] = []
    for servicio in t.servicios[1:]:
        with _sentencias(test_engine) as sentencias:
            derivados.append(await _disponibilidad(client, t, servicio))
        # Tienda + servicio con sus profesionales; la agenda del dia no.
        assert len(sentencias) <= 2, sentencias
        assert not _lee_la_agenda(sentencias), sentencias
        test_session.expunge_all()

    # Lo derivado de la agenda cacheada es lo mismo que calcula la base.
    _cache_nuevo()
    desde_la_base = [await _disponibilidad(client, t, s) for s in t.servicios[1:]]
    assert derivados == desde_la_base
    assert derivados[0], "Color tiene grilla"
    assert {s["staff_id"] for s in derivados[0]} == {t.ana}


async def _reservar(client: AsyncClient, t: _Tienda) -> None:
    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.servicios[0],
            "staff_id": t.beto,
            "starts_at": _local(t.dia, "09:30").isoformat(),
            "client_name": "Cliente Sentencias",
            "client_phone": "+5491155559001",
            "accepts_terms": True,
            "idempotency_key": f"{t.store}-publica-01",
        },
    )
    assert res.status_code == 201, res.text


async def _cancelar(client: AsyncClient, t: _Tienda) -> None:
    res = await client.patch(
        f"/appointments/{t.turno}/cancel", headers=auth_headers(t.token)
    )
    assert res.status_code == 200, res.text


async def _bloquear(client: AsyncClient, t: _Tienda) -> None:
    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(t.token),
        json={
            "staff_id": t.ana,
            "starts_at": _local(t.dia, "12:00").isoformat(),
            "ends_at": _local(t.dia, "13:00").isoformat(),
            "reason": "Medico",
        },
    )
    assert res.status_code == 201, res.text


async def _editar_servicio(client: AsyncClient, t: _Tienda) -> None:
    res = await client.patch(
        f"/services/{t.servicios[2]}",
        headers=auth_headers(t.token),
        json={"name": "Peinado largo"},
    )
    assert res.status_code == 200, res.text


CAMBIOS = {
    "reserva": _reservar,
    "cancelacion": _cancelar,
    "bloqueo": _bloquear,
    "servicio": _editar_servicio,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("cambio", sorted(CAMBIOS))
async def test_toda_invalidacion_cubre_los_dos_niveles(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    cambio: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"sentencias-inv-{cambio}")
    # Los dos niveles calientes: los slots de Corte y la agenda del dia.
    antes = await _disponibilidad(client, t, t.servicios[0])

    await CAMBIOS[cambio](client, t)
    test_session.expunge_all()
    with _sentencias(test_engine) as sentencias:
        despues = await _disponibilidad(client, t, t.servicios[0])

    # Nivel 2: la agenda del dia se vuelve a leer de la base.
    assert _lee_la_agenda(sentencias), f"{cambio}: agenda cacheada vieja"
    # Nivel 1 y resultado: lo mismo que calcula la base sin cache.
    _cache_nuevo()
    assert despues == await _disponibilidad(client, t, t.servicios[0])
    if cambio != "servicio":
        assert despues != antes, f"{cambio}: la grilla no cambio"
