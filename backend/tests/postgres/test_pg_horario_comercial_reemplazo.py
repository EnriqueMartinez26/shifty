"""Bajo Postgres real, re-guardar el horario de un dia ya abierto no da 409.

2026-09-27. Contracara de ``tests/integration/test_horario_comercial_reemplazo.py``
(ese docstring tiene el sintoma y la causa). En la base migrada NO existe
``uq_store_day_schedule`` (la borro ``c2d4e6f8a901``), asi que aca el 409 no
se reproducia antes del arreglo; este test fija que la actualizacion en su
lugar sigue funcionando con RLS forzada y el rol ``shifty_app``, y que el dia
queda con un unico periodo (§4 de CLAUDE.md: SQLite no prueba Postgres).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


def _horario(open_: str, close: str) -> dict[str, object]:
    return {"business_hours": {"mon": [{"open": open_, "close": close}]}}


@pytest.mark.asyncio
async def test_cambiar_la_hora_de_un_dia_ya_abierto_se_guarda_bajo_rls(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="h-pg-horario", email="h-pg-horario@demo.com"
    )
    headers = auth_headers(token)
    for open_ in ("09:00", "10:00", "10:00"):
        res = await client.patch(
            "/stores/me", headers=headers, json=_horario(open_, "18:00")
        )
        assert res.status_code == 200, res.text
        assert res.json()["business_hours"]["mon"] == [
            {"open": open_, "close": "18:00"}
        ]

    leido = await client.get("/stores/me", headers=headers)
    assert leido.status_code == 200, leido.text
    assert leido.json()["business_hours"]["mon"] == [
        {"open": "10:00", "close": "18:00"}
    ]
