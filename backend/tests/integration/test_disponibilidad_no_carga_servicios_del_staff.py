"""La disponibilidad no deja en la sesion un ``Staff.services`` sin filtrar.

AUD2-B6-02 (2026-09-20) + F3-02 (2026-09-24). ``PublicRepository.get_staff``
carga los servicios del profesional con el filtro de activos EN la carga
(``selectinload(Staff.services.and_(...))``): reasignar la coleccion marcaba
para DELETE las filas de ``staff_services`` de un servicio desactivado. Esa
garantia depende de que nadie haya cargado antes, en la MISMA sesion, la
coleccion completa: la sesion no refresca una coleccion ya cargada.

La disponibilidad lo hacia (``select(Staff).options(selectinload(
Staff.services))`` sin filtro): despues de consultarla, ``/public/staff``
en la misma sesion devolvia el servicio desactivado. Ahora la grilla lee los
profesionales en columnas (JOIN sobre ``staff_services``) y no carga ninguna
entidad ``Staff``.

Nota: con SQLAlchemy 2 la carga filtrada de ``get_staff`` (``.and_()``)
repuebla la coleccion, y el identity map es debil (un ``Staff`` que nadie
referencia se va con la request), asi que el listado ya salia bien; lo que
este test fija es la causa: la grilla no carga ninguna entidad ``Staff``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.staff_service import StaffServiceModel
from modules.staff.model import Staff
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _servicio(client: AsyncClient, token: str, nombre: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": 30, "price": 1000},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


@pytest.mark.asyncio
async def test_un_servicio_inactivo_no_aparece_en_el_staff_despues_de_la_grilla(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, token = await register_and_login(
        client, slug="grilla-sin-cascada", email="grilla-sin-cascada@example.com"
    )
    activo = await _servicio(client, token, "Activo")
    dado_de_baja = await _servicio(client, token, "Dado de baja")
    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro",
            "first_name": "Pro",
            "last_name": "Uno",
            "email": "pro-grilla@example.com",
            "service_ids": [activo, dado_de_baja],
        },
    )
    assert alta.status_code == 201, alta.text
    staff = alta.json()["public_id"]
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "09:00:00",
            "end_time": "12:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    baja = await client.patch(
        f"/services/{dado_de_baja}",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert baja.status_code == 200, baja.text
    # Como en un request real: la sesion arranca sin nada cargado.
    test_session.expunge_all()

    # La grilla y el listado de profesionales en la MISMA sesion.
    staff_cargados: list[object] = []

    def contar(target: object, _context: object) -> None:
        staff_cargados.append(target)

    event.listen(Staff, "load", contar)
    try:
        grilla = await client.get(
            "/public/availability",
            params={
                "store_public_id": store,
                "service_id": activo,
                "date": dia.date().isoformat(),
            },
        )
    finally:
        event.remove(Staff, "load", contar)
    assert grilla.status_code == 200, grilla.text
    assert grilla.json(), "el profesional tiene horario ese dia"
    # La grilla no carga ningun Staff (ni su coleccion de servicios): lee los
    # profesionales en columnas.
    assert staff_cargados == [], "la grilla cargo entidades Staff"
    profesionales = await client.get("/public/staff", params={"store_public_id": store})

    assert profesionales.status_code == 200, profesionales.text
    assert [p["service_ids"] for p in profesionales.json()] == [[activo]]
    # Y la asignacion al servicio dado de baja sigue en la base.
    await test_session.commit()
    asignaciones = await test_session.scalar(
        select(func.count()).select_from(StaffServiceModel)
    )
    assert asignaciones == 2
