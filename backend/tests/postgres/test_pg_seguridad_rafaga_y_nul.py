"""Suite de seguridad contra Postgres real: rafaga sin fugas y NUL en texto.

Complementa ``tests/security/`` en lo que SQLite no puede probar:

- Rafaga concurrente sobre un mismo turno (CLAUDE.md §4: N a la vez, 1
  exito, N-1 conflictos, cero 5xx). Reusa los helpers de
  ``test_pg_reserva_concurrente.py`` y agrega lo que mira la suite de
  seguridad: los N-1 rechazos salen en el sobre canonico y no le cuentan a
  ningun perdedor quien se quedo con el turno.
- Un NUL (U+0000) en un campo de texto: SQLite lo guarda, Postgres lo
  rechaza con SQLSTATE 22021 y la app responde 500. En
  ``tests/security/test_entrada_hostil.py`` el caso se infiere; aca se
  reproduce de punta a punta por el camino anonimo.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.test_pg_reserva_concurrente import (
    RAFAGA,
    _reserva,
    _tienda_reservable,
    _turnos_activos,
)
from tests.security.verificacion import Defecto, exigir, problemas_del_error

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_rafaga_sobre_un_turno_no_le_cuenta_al_perdedor_quien_gano(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "seguridad-rafaga"
    )
    cuerpos = [
        _reserva(store, service, staff, slot, i, f"seg-rafaga-{i:02d}")
        for i in range(RAFAGA)
    ]
    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo) for cuerpo in cuerpos)
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert set(codigos) <= {201, 409}, codigos
    assert await _turnos_activos(owner_engine, staff) == 1

    cuerpo_ganador, respuesta_ganadora = next(
        (cuerpo, r) for cuerpo, r in zip(cuerpos, respuestas) if r.status_code == 201
    )
    datos_del_ganador = {
        cuerpo_ganador["client_name"],
        cuerpo_ganador["client_phone"].lstrip("+"),
        respuesta_ganadora.json()["public_id"],
    }
    for respuesta in respuestas:
        if respuesta.status_code == 201:
            continue
        assert not problemas_del_error(respuesta), respuesta.text
        filtrado = [dato for dato in datos_del_ganador if dato in respuesta.text]
        assert not filtrado, f"un rechazo cuenta datos del ganador: {filtrado}"


@pytest.mark.asyncio
async def test_un_nul_en_la_reserva_publica_no_es_un_500(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "seguridad-nul"
    )
    cuerpo = _reserva(store, service, staff, slot, 1, "clave-con-nul-" + chr(0))

    try:
        res = await client.post("/public/appointments", json=cuerpo)
    except Exception as exc:
        # El transport del conftest re-levanta la excepcion del 500 en vez de
        # devolver la respuesta: para el cliente real es el mismo 500.
        raise Defecto(f"NUL en la reserva publica: {type(exc).__name__}") from exc

    exigir(res.status_code == 422, f"NUL en la reserva: {res.status_code} {res.text}")
