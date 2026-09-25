"""Las colecciones de Staff y Store se cargan solo donde se usan.

F3-01 (plan de rendimiento, R2-07 y nota de R1, 2026-09-24). Sintoma:
``Staff.schedules``, ``Staff.services`` y ``Store.schedules`` eran
``lazy="selectin"``, asi que CADA ``select(Staff)`` sumaba dos SELECT (franjas
y servicios) y cada ``select(Store)`` uno (horario comercial), los usara el
llamador o no. La agenda diaria del panel, que solo lee ``display_name`` del
profesional, pagaba 3 sentencias en lugar de 1; el catalogo publico de
profesionales, 5 en lugar de 3. Lo mismo en reportes, recordatorios, jobs del
outbox, lista de espera, etc.

Ahora las tres son ``lazy="raise"``: quien necesita la coleccion la pide con
``selectinload`` y un acceso sin cargar revienta en lugar de disparar una
consulta escondida (o un ``MissingGreenlet`` en async). La sesion de los tests
se comparte con los requests, asi que antes de contar se vacia el identity
map: si no, una coleccion ya cargada en el armado esconderia la consulta.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.staff.model import Staff
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

_COLECCIONES = re.compile(r"\b(schedules|store_schedules|staff_services)\b")


def _es_de_identidad(statement: str) -> bool:
    texto = " ".join(statement.split()).lower()
    return "auth_sessions" in texto


@contextmanager
def _contar_sentencias(engine: AsyncEngine) -> Iterator[list[str]]:
    sentencias: list[str] = []

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if not _es_de_identidad(statement):
            sentencias.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        yield sentencias
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)


def test_las_tres_colecciones_no_se_cargan_solas() -> None:
    relaciones = {
        "Staff.schedules": inspect(Staff).relationships["schedules"],
        "Staff.services": inspect(Staff).relationships["services"],
        "Store.schedules": inspect(Store).relationships["schedules"],
    }
    estrategias = {nombre: rel.lazy for nombre, rel in relaciones.items()}
    assert estrategias == {nombre: "raise" for nombre in relaciones}, estrategias


async def _tienda_con_turno(client: AsyncClient) -> tuple[str, str, str, str]:
    """Tienda con horario comercial, un profesional con franja y un turno."""
    store, token = await register_and_login(
        client, slug="colecciones", email="colecciones@example.com"
    )
    horario = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"business_hours": {"mon": [{"open": "09:00", "close": "18:00"}]}},
    )
    assert horario.status_code == 200, horario.text
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-col@example.com")
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    franja = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "10:00:00",
            "end_time": "18:00:00",
        },
    )
    assert franja.status_code == 200, franja.text
    slots = (
        await client.get(
            "/public/availability",
            params={
                "store_public_id": store,
                "service_id": service,
                "date": dia.isoformat(),
                "force_all": "true",
            },
        )
    ).json()
    slot = next(s for s in slots if s["start_time"] == "12:00:00")
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot["starts_at"],
            "client_name": "Colecciones",
            "client_phone": "+5491155550909",
            "accepts_terms": True,
            "idempotency_key": "colecciones-1200",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return store, token, service, dia.isoformat()


@pytest.mark.asyncio
async def test_la_agenda_diaria_no_carga_franjas_ni_servicios(
    client: AsyncClient, test_engine: AsyncEngine, test_session: AsyncSession
) -> None:
    _, token, _, dia = await _tienda_con_turno(client)
    test_session.expunge_all()

    with _contar_sentencias(test_engine) as sentencias:
        agenda = await client.get(
            "/appointments/", params={"date": dia}, headers=auth_headers(token)
        )

    assert agenda.status_code == 200, agenda.text
    assert len(agenda.json()) == 1, agenda.text
    assert agenda.json()[0]["staff_name"] == "Pro Demo"
    # Antes: el SELECT de la agenda + franjas + servicios del profesional.
    assert len(sentencias) == 1, sentencias
    assert not [s for s in sentencias if _COLECCIONES.search(s)], sentencias


@pytest.mark.asyncio
async def test_el_catalogo_publico_de_profesionales_carga_solo_servicios(
    client: AsyncClient, test_engine: AsyncEngine, test_session: AsyncSession
) -> None:
    store, _, service, _ = await _tienda_con_turno(client)
    test_session.expunge_all()

    with _contar_sentencias(test_engine) as sentencias:
        respuesta = await client.get("/public/staff", params={"store_public_id": store})

    assert respuesta.status_code == 200, respuesta.text
    assert [m["service_ids"] for m in respuesta.json()] == [[service]]
    # Tienda + profesionales + sus servicios activos. Antes sumaba el horario
    # comercial de la tienda y las franjas de cada profesional.
    assert len(sentencias) == 3, sentencias
    tocadas = [m.group(1) for s in sentencias for m in _COLECCIONES.finditer(s)]
    assert set(tocadas) == {"staff_services"}, sentencias


@pytest.mark.asyncio
async def test_la_configuracion_de_la_tienda_carga_el_horario_explicito(
    client: AsyncClient, test_engine: AsyncEngine, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="colecciones-tienda", email="colecciones-tienda@example.com"
    )
    guardado = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"business_hours": {"tue": [{"open": "08:00", "close": "12:00"}]}},
    )
    assert guardado.status_code == 200, guardado.text
    assert guardado.json()["business_hours"]["tue"] == [
        {"open": "08:00", "close": "12:00"}
    ]
    test_session.expunge_all()

    with _contar_sentencias(test_engine) as de_la_ficha:
        tienda = await client.get("/stores/me", headers=auth_headers(token))
    test_session.expunge_all()
    with _contar_sentencias(test_engine) as de_las_banderas:
        banderas = await client.get(
            "/stores/me/feature-flags", headers=auth_headers(token)
        )

    assert tienda.status_code == 200, tienda.text
    assert banderas.status_code == 200, banderas.text
    assert tienda.json()["business_hours"]["tue"] == [
        {"open": "08:00", "close": "12:00"}
    ]
    # La ficha lee el horario con su carga explicita; las banderas no.
    assert [s for s in de_la_ficha if "store_schedules" in s] != [], de_la_ficha
    assert [s for s in de_las_banderas if "store_schedules" in s] == [], de_las_banderas


@pytest.mark.asyncio
async def test_la_guarda_del_fiado_lee_solo_las_banderas_de_la_tienda(
    client: AsyncClient, test_engine: AsyncEngine, test_session: AsyncSession
) -> None:
    """La guarda de la funcion de fiado no necesita la fila entera de la tienda."""
    _, token = await register_and_login(
        client, slug="colecciones-fiado", email="colecciones-fiado@example.com"
    )
    test_session.expunge_all()

    with _contar_sentencias(test_engine) as sentencias:
        respuesta = await client.get("/ledger/summary", headers=auth_headers(token))

    # Tienda sin la funcion activa: la guarda corta antes de las sumas.
    assert respuesta.status_code == 403, respuesta.text
    de_tienda = [s for s in sentencias if re.search(r"\bFROM stores\b", s)]
    assert len(de_tienda) == 1, sentencias
    assert de_tienda[0].startswith("SELECT stores.feature_flags FROM stores"), de_tienda


@pytest.mark.asyncio
async def test_editar_los_servicios_del_profesional_sin_nada_en_memoria(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """``_set_services`` reasigna la coleccion: exige el Staff de ``get_by_id``.

    Con el identity map vacio nada viene cargado del armado: si el camino no
    cargara ``services`` antes de reasignarla, ``lazy="raise"`` lo cortaria.
    """
    _, token = await register_and_login(
        client, slug="colecciones-staff", email="colecciones-staff@example.com"
    )
    corte = await create_service(client, token)
    color = await create_service(client, token)
    staff = await create_staff(client, token, corte, email="pro-cs@example.com")

    test_session.expunge_all()
    parche = await client.patch(
        f"/staff/{staff}/services", headers=auth_headers(token), json=[color]
    )
    assert parche.status_code == 200, parche.text

    test_session.expunge_all()
    perfil = await client.patch(
        f"/staff/{staff}",
        headers=auth_headers(token),
        json={"service_ids": [corte, color]},
    )
    assert perfil.status_code == 200, perfil.text
    assert sorted(perfil.json()["service_ids"]) == sorted([corte, color])

    test_session.expunge_all()
    ficha = await client.get(f"/staff/{staff}", headers=auth_headers(token))
    assert ficha.status_code == 200, ficha.text
    assert sorted(ficha.json()["service_ids"]) == sorted([corte, color])
