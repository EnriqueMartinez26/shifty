"""Busqueda de turnos: el total cuesta un COUNT sobre ``appointments`` y es
opcional; el resumen de reportes puede pedir el detalle de lo mas reciente.

2026-09-24, plan de rendimiento F3-06 (hallazgos R2-05 y R6-03).

- ``/appointments/search`` contaba con ``SELECT count(*) FROM (<la consulta
  de la pagina con sus cuatro entidades>)`` en CADA pagina, y el panel pide
  las paginas en serie: el mismo total se recalculaba N veces con joins a
  ``services``, ``staff`` y ``users`` que no cambian el conteo. Ahora es
  ``count(appointments.id)`` con el mismo ``WHERE``; ``users`` entra solo si
  filtra ``client_name`` y ``services`` solo si filtra ``service_id``. Sin el
  join a ``users`` se exige ``client_id IS NOT NULL``: la pagina hace inner
  join a ``users``, y el total tiene que contar las mismas filas.
  ``include_total=false`` (aditivo) evita el conteo en las paginas 2 en
  adelante. La pagina lee del profesional solo ``id`` y ``display_name``: sin
  los ``selectin`` de sus relaciones.
- ``/reports/summary`` ordenaba el detalle siempre ascendente, asi que el
  Dashboard no podia pedir "los 6 mas recientes" con ``limit``: traia 2000
  filas para mostrar 6. ``order=desc`` (aditivo) invierte el orden estable
  ``(starts_at, id)``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda


class _Registro:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sentencias: list[str] = []

    def _registrar(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        self.sentencias.append(" ".join(statement.lower().split()))

    def __enter__(self) -> list[str]:
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._registrar)
        return self.sentencias

    def __exit__(self, *_: object) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._registrar)


async def _sembrar(
    client: AsyncClient, test_session: AsyncSession
) -> tuple[str, list[str]]:
    """Cinco turnos con cliente (dos a la misma hora) y uno sin cliente."""
    token, store, staff, corto = await _tienda(client, test_session, "f306-busq")
    semilla = _Semilla(test_session, store, staff)
    ana = semilla.cliente("Ana", "Busqueda")
    beto = semilla.cliente("Beto", "Otro")
    await test_session.commit()
    ids = []
    for indice, (dia, hora, cliente) in enumerate(
        [
            (date(2026, 9, 1), time(10, 0), ana),
            (date(2026, 9, 2), time(10, 0), beto),
            (date(2026, 9, 3), time(10, 0), ana),
            (date(2026, 9, 3), time(10, 0), beto),  # misma hora que el anterior
            (date(2026, 9, 4), time(10, 0), ana),
        ]
    ):
        ids.append(
            await semilla.turno(
                f"f306-{indice}",
                dia,
                hora,
                corto,
                cliente,
                AppointmentStatus.CONFIRMED,
                precio=Decimal("10000"),
            )  # fmt: skip
        )
    inicio = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    test_session.add(
        Appointment(
            service_id=corto.id,
            staff_id=staff.id,
            store_id=store.id,
            client_id=None,
            client_name="Sin cuenta",
            starts_at=inicio,
            ends_at=inicio + timedelta(minutes=30),
            duration_minutes=30,
            status=AppointmentStatus.CONFIRMED.value,
            idempotency_key="f306-huerfano",
        )
    )
    await test_session.commit()
    return token, ids


def _de_turnos(sentencias: list[str]) -> list[str]:
    return [s for s in sentencias if "from appointments" in s]


@pytest.mark.asyncio
async def test_el_total_de_la_busqueda_es_un_count_sin_entidades(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    token, _ = await _sembrar(client, test_session)
    with _Registro(test_engine) as sentencias:
        res = await client.get(
            "/appointments/search",
            params={"page": 1, "page_size": 2},
            headers=auth_headers(token),
        )
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    # El turno sin cliente nunca aparece en los resultados, asi que el total
    # tampoco lo cuenta.
    assert cuerpo["total"] == 5
    assert len(cuerpo["results"]) == 2
    turnos = _de_turnos(sentencias)
    conteos = [s for s in turnos if "count(" in s]
    assert len(conteos) == 1, turnos
    (conteo,) = conteos
    assert " join " not in conteo, conteo
    assert "appointments.client_id is not null" in conteo, conteo
    assert "appointments.store_id" in conteo, conteo
    # Sin los selectin de Staff: nada toca staff_services ni schedules.
    assert not [s for s in sentencias if "staff_services" in s], sentencias
    assert len(turnos) == 2, turnos

    # Con client_name el conteo une users (y nada mas).
    with _Registro(test_engine) as sentencias:
        res = await client.get(
            "/appointments/search",
            params={"client_name": "busqueda"},
            headers=auth_headers(token),
        )
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 3
    (conteo,) = [s for s in _de_turnos(sentencias) if "count(" in s]
    assert " join users " in conteo, conteo
    assert " join services " not in conteo and " join staff " not in conteo


@pytest.mark.asyncio
async def test_include_total_false_no_cuenta(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    token, _ = await _sembrar(client, test_session)
    con_total = await client.get(
        "/appointments/search",
        params={"page": 2, "page_size": 2},
        headers=auth_headers(token),
    )
    with _Registro(test_engine) as sentencias:
        sin_total = await client.get(
            "/appointments/search",
            params={"page": 2, "page_size": 2, "include_total": "false"},
            headers=auth_headers(token),
        )
    assert sin_total.status_code == 200, sin_total.text
    assert sin_total.json()["total"] is None
    assert sin_total.json()["results"] == con_total.json()["results"]
    assert [s for s in _de_turnos(sentencias) if "count(" in s] == []


@pytest.mark.asyncio
async def test_el_resumen_puede_pedir_lo_mas_reciente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, ids = await _sembrar(client, test_session)
    rango = {"from_date": "2026-09-01", "to_date": "2026-09-04"}
    ascendente = await client.get(
        "/reports/summary", params=rango, headers=auth_headers(token)
    )
    assert ascendente.status_code == 200, ascendente.text
    orden = [i["public_id"] for i in ascendente.json()["appointments"]]
    # Default sin cambios: ascendente por (starts_at, id).
    assert orden[0] == ids[0] and orden[-1] == ids[-1]

    recientes = await client.get(
        "/reports/summary",
        params={**rango, "order": "desc", "limit": 3},
        headers=auth_headers(token),
    )
    assert recientes.status_code == 200, recientes.text
    cuerpo = recientes.json()
    assert [i["public_id"] for i in cuerpo["appointments"]] == list(reversed(orden))[:3]
    assert cuerpo["has_more"] is True
    # Los totales no dependen del orden.
    assert cuerpo["stats"] == ascendente.json()["stats"]

    invalido = await client.get(
        "/reports/summary",
        params={**rango, "order": "random"},
        headers=auth_headers(token),
    )
    assert invalido.status_code == 422, invalido.text
