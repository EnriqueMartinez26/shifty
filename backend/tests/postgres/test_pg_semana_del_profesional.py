"""Reemplazo de la semana del profesional en rafaga, contra Postgres real.

2026-10-08 (``PUT /staff/{public_id}/schedules``). Lo que SQLite no prueba:

- El ``DELETE`` + ``INSERT`` del reemplazo corre como ``shifty_app`` bajo RLS.
- Dos reemplazos a la vez sobre el mismo profesional no mezclan sus cuerpos.
  Sin el ``SELECT ... FOR UPDATE`` de la fila del profesional, en READ
  COMMITTED cada transaccion borraba solo las franjas que veia su foto y la
  semana terminaba con la union de los dos cuerpos.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from modules.staff.repository import StaffRepository
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = min(int(os.getenv("TEST_POSTGRES_RAFAGA", "25")), 10)


def _semana(i: int) -> dict[str, Any]:
    """Cuerpo distinguible: los minutos del cierre identifican al pedido."""
    return {
        "schedules": [
            {"day_of_week": 1, "start_time": "06:00:00", "end_time": f"08:{i:02d}:00"},
            {"day_of_week": 3, "start_time": "10:00:00", "end_time": f"12:{i:02d}:00"},
        ]
    }


@pytest.mark.asyncio
async def test_rafaga_de_reemplazos_deja_una_sola_semana_entera(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-semana", email="pg-semana@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-pg-semana@demo.com")

    respuestas = await asyncio.gather(
        *(
            client.put(
                f"/staff/{staff}/schedules",
                headers=auth_headers(token),
                json=_semana(i),
            )
            for i in range(RAFAGA)
        )
    )

    assert sorted(r.status_code for r in respuestas) == [200] * RAFAGA, [
        r.text for r in respuestas if r.status_code != 200
    ]
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "select day_of_week, end_time from schedules "
                    "where staff_id = :staff order by day_of_week"
                ),
                {"staff": staff},
            )
        ).all()
    # Exactamente la semana de UN pedido: dos franjas con los mismos minutos.
    assert [fila.day_of_week for fila in filas] == [1, 3], filas
    assert len({fila.end_time.minute for fila in filas}) == 1, filas


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operacion", "estado_esperado"),
    [("post", 422), ("patch", 404), ("delete", 404)],
)
async def test_reemplazo_semanal_serializa_las_mutaciones_de_franjas(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    operacion: str,
    estado_esperado: int,
) -> None:
    """Una mutacion individual espera al PUT y consulta la semana ya confirmada.

    Se pausa el PUT despues de borrar e insertar, pero antes del commit. La
    segunda request llega a intentar el lock mientras esos cambios aun no son
    visibles. POST debe detectar el solapamiento con la semana nueva; PATCH y
    DELETE deben releer y responder 404 porque el PUT reemplazo la fila vieja.
    Sin lock comun, las tres rutas observan/modifican el estado anterior.
    """
    _store, token = await register_and_login(
        client,
        app_sessions,
        slug=f"pg-semana-race-{operacion}",
        email=f"pg-semana-race-{operacion}@demo.com",
    )
    service = await create_service(client, token)
    staff = await create_staff(
        client, token, service, email=f"pro-pg-semana-race-{operacion}@demo.com"
    )
    headers = auth_headers(token)
    original = await client.post(
        f"/staff/{staff}/schedules",
        headers=headers,
        json={"day_of_week": 1, "start_time": "06:00:00", "end_time": "08:00:00"},
    )
    assert original.status_code == 200, original.text
    old_schedule_id = original.json()["public_id"]

    reemplazo_escrito = asyncio.Event()
    permitir_commit = asyncio.Event()
    segundo_lock_intentado = asyncio.Event()
    lock_count = 0
    original_replace = StaffRepository.replace_schedules
    original_lock = StaffRepository.lock_staff

    async def pause_after_replace(
        repo: StaffRepository, profesional: Any, franjas: list[dict[str, Any]]
    ) -> Any:
        resultado = await original_replace(repo, profesional, franjas)
        reemplazo_escrito.set()
        await permitir_commit.wait()
        return resultado

    async def observe_lock_attempt(repo: StaffRepository, profesional: Any) -> None:
        nonlocal lock_count
        lock_count += 1
        if lock_count == 2:
            segundo_lock_intentado.set()
        await original_lock(repo, profesional)

    monkeypatch.setattr(StaffRepository, "replace_schedules", pause_after_replace)
    monkeypatch.setattr(StaffRepository, "lock_staff", observe_lock_attempt)

    tarea_put = asyncio.create_task(
        client.put(
            f"/staff/{staff}/schedules",
            headers=headers,
            json={
                "schedules": [
                    {
                        "day_of_week": 1,
                        "start_time": "10:00:00",
                        "end_time": "12:00:00",
                    }
                ]
            },
        )
    )
    tarea_mutacion: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(reemplazo_escrito.wait(), timeout=10)
        if operacion == "post":
            tarea_mutacion = asyncio.create_task(
                client.post(
                    f"/staff/{staff}/schedules",
                    headers=headers,
                    json={
                        "day_of_week": 1,
                        "start_time": "10:30:00",
                        "end_time": "11:30:00",
                    },
                )
            )
        elif operacion == "patch":
            tarea_mutacion = asyncio.create_task(
                client.patch(
                    f"/staff/{staff}/schedules/{old_schedule_id}",
                    headers=headers,
                    json={
                        "start_time": "10:30:00",
                        "end_time": "11:30:00",
                    },
                )
            )
        else:
            tarea_mutacion = asyncio.create_task(
                client.delete(
                    f"/staff/{staff}/schedules/{old_schedule_id}", headers=headers
                )
            )

        await asyncio.wait_for(segundo_lock_intentado.wait(), timeout=10)
        assert not tarea_mutacion.done(), "la mutacion no espero al lock del PUT"
    finally:
        permitir_commit.set()
        tareas = [tarea_put]
        if tarea_mutacion is not None:
            tareas.append(tarea_mutacion)
        await asyncio.wait_for(
            asyncio.gather(*tareas, return_exceptions=True), timeout=10
        )

    respuesta_put = tarea_put.result()
    assert respuesta_put.status_code == 200, respuesta_put.text
    assert tarea_mutacion is not None
    respuesta_mutacion = tarea_mutacion.result()
    assert respuesta_mutacion.status_code == estado_esperado, respuesta_mutacion.text

    horarios = await client.get(f"/staff/{staff}", headers=headers)
    assert horarios.status_code == 200, horarios.text
    assert [
        (item["day_of_week"], item["start_time"], item["end_time"])
        for item in horarios.json()["schedules"]
    ] == [(1, "10:00:00", "12:00:00")]


@pytest.mark.asyncio
async def test_dos_patch_parciales_conservan_cambios_de_ambas_requests(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El segundo PATCH parcial parte de los valores releidos tras el lock.

    La segunda request precarga la franja antes de esperar el lock. A cambia
    ``start_time`` y se pausa antes del commit; B cambia solo ``end_time``.
    Al continuar, B tiene que conservar el inicio confirmado por A.
    """
    _store, token = await register_and_login(
        client,
        app_sessions,
        slug="pg-semana-patch-parcial",
        email="pg-semana-patch-parcial@demo.com",
    )
    service = await create_service(client, token)
    staff = await create_staff(
        client, token, service, email="pro-pg-semana-patch-parcial@demo.com"
    )
    headers = auth_headers(token)
    original = await client.post(
        f"/staff/{staff}/schedules",
        headers=headers,
        json={"day_of_week": 1, "start_time": "06:00:00", "end_time": "08:00:00"},
    )
    assert original.status_code == 200, original.text
    schedule_id = original.json()["public_id"]

    primer_patch_escrito = asyncio.Event()
    permitir_commit = asyncio.Event()
    segundo_lock_intentado = asyncio.Event()
    lock_count = 0
    update_count = 0
    original_update = StaffRepository.update_schedule
    original_lock = StaffRepository.lock_staff

    async def pause_first_update(
        repo: StaffRepository,
        profesional: Any,
        schedule: Any,
        cambios: dict[str, Any],
    ) -> Any:
        nonlocal update_count
        resultado = await original_update(repo, profesional, schedule, cambios)
        update_count += 1
        if update_count == 1:
            primer_patch_escrito.set()
            await permitir_commit.wait()
        return resultado

    async def observe_lock_attempt(repo: StaffRepository, profesional: Any) -> None:
        nonlocal lock_count
        lock_count += 1
        if lock_count == 2:
            segundo_lock_intentado.set()
        await original_lock(repo, profesional)

    monkeypatch.setattr(StaffRepository, "update_schedule", pause_first_update)
    monkeypatch.setattr(StaffRepository, "lock_staff", observe_lock_attempt)

    tarea_inicio = asyncio.create_task(
        client.patch(
            f"/staff/{staff}/schedules/{schedule_id}",
            headers=headers,
            json={"start_time": "07:00:00"},
        )
    )
    tarea_fin: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(primer_patch_escrito.wait(), timeout=10)
        tarea_fin = asyncio.create_task(
            client.patch(
                f"/staff/{staff}/schedules/{schedule_id}",
                headers=headers,
                json={"end_time": "12:00:00"},
            )
        )
        await asyncio.wait_for(segundo_lock_intentado.wait(), timeout=10)
        assert not tarea_fin.done(), "el segundo PATCH no espero al lock"
    finally:
        permitir_commit.set()
        tareas = [tarea_inicio]
        if tarea_fin is not None:
            tareas.append(tarea_fin)
        await asyncio.wait_for(
            asyncio.gather(*tareas, return_exceptions=True), timeout=10
        )

    respuesta_inicio = tarea_inicio.result()
    assert respuesta_inicio.status_code == 200, respuesta_inicio.text
    assert tarea_fin is not None
    respuesta_fin = tarea_fin.result()
    assert respuesta_fin.status_code == 200, respuesta_fin.text
    assert respuesta_fin.json()["start_time"] == "07:00:00"
    assert respuesta_fin.json()["end_time"] == "12:00:00"

    horarios = await client.get(f"/staff/{staff}", headers=headers)
    assert horarios.status_code == 200, horarios.text
    assert [
        (item["start_time"], item["end_time"]) for item in horarios.json()["schedules"]
    ] == [("07:00:00", "12:00:00")]
