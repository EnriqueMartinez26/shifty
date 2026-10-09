"""Re-guardar el horario de un dia que YA tiene fila no choca con el UNIQUE.

2026-09-27. Sintoma: el segundo ``PATCH /stores/me`` con ``business_hours``
para un dia ya abierto (lunes 09-18 -> 10-18, o el mismo 09-18 de nuevo)
respondia 409 ``RESOURCE_CONFLICT`` y el horario no cambiaba. Causa:
``_replace_business_hours`` hacia ``store.schedules.clear()`` y agregaba filas
nuevas; en un mismo flush SQLAlchemy emite los INSERT antes que los DELETE de
los huerfanos, asi que la fila nueva del lunes chocaba con
``uq_store_day_schedule`` (``store_id, day_of_week``) antes de que se borrara
la vieja. Los tests de horario existentes partian siempre de un dia vacio.

Donde se ve: el esquema del modelo (el de esta suite). En Postgres la
migracion ``c2d4e6f8a901`` borro ese UNIQUE (deriva declarada en
``tests/postgres/test_pg_modelo_y_migraciones.py``), por eso alli no fallaba;
el arreglo actualiza la fila del dia en su lugar y es correcto con o sin la
restriccion.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


def _horario(open_: str, close: str) -> dict[str, object]:
    return {"business_hours": {"mon": [{"open": open_, "close": close}]}}


@pytest.mark.asyncio
async def test_cambiar_la_hora_de_un_dia_ya_abierto_se_guarda(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="horario-reemplazo", email="horario-reemplazo@test.com"
    )
    headers = auth_headers(token)
    primero = await client.patch(
        "/stores/me", headers=headers, json=_horario("09:00", "18:00")
    )
    assert primero.status_code == 200, primero.text

    segundo = await client.patch(
        "/stores/me", headers=headers, json=_horario("10:00", "18:00")
    )
    assert segundo.status_code == 200, segundo.text
    esperado = [{"open": "10:00", "close": "18:00"}]
    assert segundo.json()["business_hours"]["mon"] == esperado

    leido = await client.get("/stores/me", headers=headers)
    assert leido.status_code == 200, leido.text
    assert leido.json()["business_hours"]["mon"] == esperado


@pytest.mark.asyncio
async def test_cerrar_un_dia_y_abrir_otro_en_el_mismo_patch(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="horario-cambio", email="horario-cambio@test.com"
    )
    headers = auth_headers(token)
    primero = await client.patch(
        "/stores/me", headers=headers, json=_horario("09:00", "18:00")
    )
    assert primero.status_code == 200, primero.text

    otro_dia = {"business_hours": {"tue": [{"open": "08:00", "close": "12:00"}]}}
    res = await client.patch("/stores/me", headers=headers, json=otro_dia)
    assert res.status_code == 200, res.text
    assert res.json()["business_hours"]["mon"] == []
    assert res.json()["business_hours"]["tue"] == [{"open": "08:00", "close": "12:00"}]


@pytest.mark.asyncio
async def test_reenviar_el_mismo_horario_es_idempotente(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="horario-mismo", email="horario-mismo@test.com"
    )
    headers = auth_headers(token)
    for _ in range(2):
        res = await client.patch(
            "/stores/me", headers=headers, json=_horario("09:00", "18:00")
        )
        assert res.status_code == 200, res.text
        assert res.json()["business_hours"]["mon"] == [
            {"open": "09:00", "close": "18:00"}
        ]
