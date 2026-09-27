"""AUD2-B6-02 (2026-09-20): una lectura del portal publico borraba filas de staff_services.

Sintoma: con un servicio desactivado (borrado logico), bastaba UNA lectura del
staff publico -o una reserva publica, que pasa por el mismo camino- para que
las filas de ``staff_services`` de ese servicio se borraran fisicamente en el
commit siguiente. ``PublicRepository.get_staff`` filtraba los activos
RE-ASIGNANDO ``member.services``; asignar sobre una relacion ``secondary``
marca las filas sobrantes para DELETE. El dueno reactivaba el servicio (el
unico mecanismo de reversion del borrado logico) y volvia sin ningun
profesional asignado: no aparecia en la pagina publica, la disponibilidad
daba vacio y no habia error en ninguna parte que lo explicara. De paso se
perdia la columna ``rating`` de esa relacion.

Los tests de integracion comparten UNA sesion entre requests (ver
``tests/integration/conftest.py``), igual que la request real comparte la
sesion entre la lectura y su commit: por eso el commit explicito de abajo
reproduce exactamente lo que hace ``POST /public/bookings``.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from infrastructure.persistence.models.staff_service import StaffServiceModel
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _crear_servicio(client: AsyncClient, token: str, nombre: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": 30, "price": 1500},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _contar_asignaciones(session: AsyncSession) -> int:
    res = await session.execute(select(func.count()).select_from(StaffServiceModel))
    return int(res.scalar_one())


async def _escenario(client: AsyncClient, slug: str) -> tuple[str, str, str, str, str]:
    """Tienda con un profesional que hace dos servicios; uno queda borrado."""
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    vivo = await _crear_servicio(client, token, "Corte")
    borrado = await _crear_servicio(client, token, "Color")
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro Demo",
            "first_name": "Pro",
            "last_name": "Demo",
            "email": f"pro-{slug}@example.com",
            "service_ids": [vivo, borrado],
        },
    )
    assert res.status_code == 201, res.text
    staff_id = cast(str, res.json()["public_id"])

    res = await client.delete(f"/services/{borrado}", headers=auth_headers(token))
    assert res.status_code == 204, res.text
    return store_public_id, token, staff_id, vivo, borrado


@pytest.mark.asyncio
async def test_leer_el_staff_publico_no_borra_la_asignacion(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token, staff_id, vivo, borrado = await _escenario(
        client, "aud2-b6-02-publico"
    )
    assert await _contar_asignaciones(test_session) == 2

    res = await client.get("/public/staff", params={"store_public_id": store_public_id})
    assert res.status_code == 200, res.text
    fichas = [m for m in res.json() if m["public_id"] == staff_id]
    # El portal sigue sin mostrar el servicio borrado: se filtra, no se borra.
    assert fichas and fichas[0]["service_ids"] == [vivo]

    # Lo que hace `POST /public/bookings` despues de leer el staff.
    await test_session.commit()
    assert await _contar_asignaciones(test_session) == 2


@pytest.mark.asyncio
async def test_reactivar_el_servicio_lo_devuelve_con_su_profesional(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token, staff_id, vivo, borrado = await _escenario(
        client, "aud2-b6-02-revertir"
    )

    res = await client.get("/public/staff", params={"store_public_id": store_public_id})
    assert res.status_code == 200, res.text
    await test_session.commit()

    reactivar = await client.patch(
        f"/services/{borrado}",
        headers=auth_headers(token),
        json={"is_active": True},
    )
    assert reactivar.status_code == 200, reactivar.text

    ficha = await client.get(f"/staff/{staff_id}", headers=auth_headers(token))
    assert ficha.status_code == 200, ficha.text
    assert sorted(ficha.json()["service_ids"]) == sorted([vivo, borrado])

    publico = await client.get(
        "/public/staff",
        params={"store_public_id": store_public_id, "service_id": borrado},
    )
    assert publico.status_code == 200, publico.text
    assert [m["public_id"] for m in publico.json()] == [staff_id]


@pytest.mark.asyncio
async def test_el_rating_de_la_asignacion_sobrevive(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La fila no solo existe: conserva su columna propia."""
    store_public_id, _, staff_id, _, borrado = await _escenario(
        client, "aud2-b6-02-rating"
    )
    fila = await test_session.execute(
        select(StaffServiceModel).where(StaffServiceModel.staff_id == staff_id)
    )
    asignaciones = list(fila.scalars().all())
    assert len(asignaciones) == 2
    for asignacion in asignaciones:
        asignacion.rating = 4.5
    await test_session.commit()

    res = await client.get("/public/staff", params={"store_public_id": store_public_id})
    assert res.status_code == 200, res.text
    await test_session.commit()

    res_rating = await test_session.execute(
        select(StaffServiceModel.rating).where(StaffServiceModel.staff_id == staff_id)
    )
    ratings = sorted(float(r) for r in res_rating.scalars().all() if r is not None)
    assert ratings == [4.5, 4.5], f"se perdio una asignacion o su rating: {ratings}"
    assert borrado  # el servicio borrado sigue teniendo su fila


@pytest.mark.asyncio
async def test_la_lectura_publica_no_reintroduce_el_n_mas_1_ni_borra_filas(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """Guarda viva: el batch que mato el N+1 (69a256f) no vuelve como bucle.

    La correccion reemplaza el batch en memoria por un filtro en el JOIN, asi
    que la carga de servicios sigue siendo UNA sola sentencia y ningun DELETE
    toca ``staff_services``.
    """
    store_public_id, _, _, _, _ = await _escenario(client, "aud2-b6-02-n1")

    sentencias: list[str] = []

    def _registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.split()).lower())

    event.listen(test_engine.sync_engine, "before_cursor_execute", _registrar)
    try:
        publico = await client.get(
            "/public/staff", params={"store_public_id": store_public_id}
        )
        await test_session.commit()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _registrar)

    assert publico.status_code == 200, publico.text
    cargas = [s for s in sentencias if s.startswith("select") and "services" in s]
    assert len(cargas) == 1, f"se esperaba una sola carga de servicios: {sentencias}"
    borrados = [s for s in sentencias if s.startswith("delete from staff_services")]
    assert not borrados, f"una lectura no puede borrar asignaciones: {borrados}"
