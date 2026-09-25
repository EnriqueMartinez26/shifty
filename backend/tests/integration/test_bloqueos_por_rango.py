"""F4-07 (mitad back): ``GET /appointment-blocks/`` por rango de dias locales.

2026-09-24. Sintoma (plan-correccion-rendimiento.md, F4-07; R6-02): la agenda
bajaba TODOS los bloqueos historicos de la tienda en cada visita, activos e
inactivos, sin cota.

Contrato (aditivo): ``from_date`` y ``to_date`` (dias LOCALES, los dos o
ninguno, ``to_date - from_date`` <= 400 dias) devuelven los bloqueos que
solapan ``[local_day_start(from_date), local_day_start(to_date + 1))``;
``include_inactive`` (``false`` saca los desactivados). Sin parametros la
respuesta es la de siempre: todos, activos e inactivos.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import local_to_utc, today_local
from modules.staff.model import StaffBlock
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

DIA = today_local() + timedelta(days=10)


async def _tienda_con_bloqueos(
    client: AsyncClient, session: AsyncSession
) -> tuple[dict[str, str], dict[str, str]]:
    store, token = await register_and_login(
        client, slug="bloq-rango", email="bloq-rango@t.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-bloq-rango@t.com")
    store_id = (
        await session.execute(select(Store.id).where(Store.public_id == store))
    ).scalar_one()

    def bloqueo(
        nombre: str, inicio: datetime, fin: datetime, activo: bool = True
    ) -> StaffBlock:
        return StaffBlock(
            store_id=store_id,
            staff_id=staff,
            start_time=inicio,
            end_time=fin,
            reason=nombre,
            is_active=activo,
        )

    def local(dia: date, hora: int, minuto: int = 0) -> datetime:
        return local_to_utc(dia, time(hora, minuto))

    filas = [
        # Termina antes del rango.
        bloqueo(
            "viejo",
            local(DIA - timedelta(days=30), 9),
            local(DIA - timedelta(days=30), 10),
        ),
        # Empezo antes y cruza el primer dia del rango (vacaciones largas).
        bloqueo("vacaciones", local(DIA - timedelta(days=5), 0), local(DIA, 12)),
        # 23:00 local del ultimo dia: en UTC ya es el dia siguiente.
        bloqueo(
            "noche",
            local(DIA + timedelta(days=1), 23),
            local(DIA + timedelta(days=1), 23, 30),
        ),
        # Adentro del rango pero desactivado.
        bloqueo("apagado", local(DIA, 15), local(DIA, 16), activo=False),
        # Empieza a la medianoche local del dia siguiente al rango.
        bloqueo(
            "despues",
            local(DIA + timedelta(days=2), 0),
            local(DIA + timedelta(days=2), 1),
        ),
    ]
    session.add_all(filas)
    await session.commit()
    return auth_headers(token), {f.id: f.reason for f in filas}


def _motivos(res: Any) -> list[str]:
    assert res.status_code == 200, res.text
    return sorted(item["reason"] for item in cast(list[dict[str, Any]], res.json()))


@pytest.mark.asyncio
async def test_sin_parametros_devuelve_todo_como_siempre(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, _ = await _tienda_con_bloqueos(client, test_session)

    res = await client.get("/appointment-blocks/", headers=headers)

    assert _motivos(res) == ["apagado", "despues", "noche", "vacaciones", "viejo"]


@pytest.mark.asyncio
async def test_el_rango_es_de_dias_locales_y_trae_lo_que_solapa(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, _ = await _tienda_con_bloqueos(client, test_session)
    rango = {
        "from_date": DIA.isoformat(),
        "to_date": (DIA + timedelta(days=1)).isoformat(),
    }

    todos = await client.get("/appointment-blocks/", headers=headers, params=rango)
    activos = await client.get(
        "/appointment-blocks/",
        headers=headers,
        params={**rango, "include_inactive": "false"},
    )

    assert _motivos(todos) == ["apagado", "noche", "vacaciones"]
    assert _motivos(activos) == ["noche", "vacaciones"]


@pytest.mark.asyncio
async def test_include_inactive_sin_rango(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, _ = await _tienda_con_bloqueos(client, test_session)

    activos = await client.get(
        "/appointment-blocks/", headers=headers, params={"include_inactive": "false"}
    )
    todos = await client.get(
        "/appointment-blocks/", headers=headers, params={"include_inactive": "true"}
    )

    assert _motivos(activos) == ["despues", "noche", "vacaciones", "viejo"]
    assert _motivos(todos) == ["apagado", "despues", "noche", "vacaciones", "viejo"]


@pytest.mark.asyncio
async def test_rangos_invalidos_422(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, _ = await _tienda_con_bloqueos(client, test_session)
    hoy = DIA.isoformat()

    casos = [
        {"from_date": hoy},
        {"to_date": hoy},
        {"from_date": hoy, "to_date": (DIA - timedelta(days=1)).isoformat()},
        {"from_date": hoy, "to_date": (DIA + timedelta(days=401)).isoformat()},
    ]
    for params in casos:
        res = await client.get("/appointment-blocks/", headers=headers, params=params)
        assert res.status_code == 422, (params, res.text)

    tope = await client.get(
        "/appointment-blocks/",
        headers=headers,
        params={"from_date": hoy, "to_date": (DIA + timedelta(days=400)).isoformat()},
    )
    assert tope.status_code == 200, tope.text
