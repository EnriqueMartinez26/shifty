"""Un deadlock o una falla de serializacion de Postgres responde 409, no 500.

Seguimiento S-18 (2026-09-19). Quedan dos caminos que pueden cruzar locks:
reprogramar (turno -> profesional) contra el alta de bloqueos (profesionales
-> turnos del rango), y el segundo lock del alta publica contra un cierre de
tienda. Postgres detecta el ciclo y aborta una transaccion con SQLSTATE 40P01
(``DeadlockDetectedError``), que SQLAlchemy envuelve en ``DBAPIError``; hoy
salia por el handler generico como 500. Es una carrera legitima entre dos
actores, igual que el optimistic locking: 409 neutro, sin detalles internos
(regla 20). Lo mismo con 40001 (``SerializationFailure``). Cualquier otro
error de base sigue siendo 500.

La carrera real esta en tests/postgres/test_pg_deadlock_como_conflicto.py; aca
se simula el error que sube de la base.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, OperationalError

import modules.notifications.tasks as tasks
from main import app
from modules.public_api.service import PublicBookingService
from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_mails_al_cliente import Buzon


class _ErrorDelDriver(Exception):
    """Como el error adaptado de asyncpg: expone ``sqlstate``."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"detalle interno del driver ({sqlstate}) SELECT secreto")
        self.sqlstate = sqlstate


def _que_falle_con(error: Exception) -> Any:
    async def book(self: PublicBookingService, *args: Any, **kwargs: Any) -> Any:
        raise error

    return book


CUERPO_NEUTRO = {
    "success": False,
    "error_code": "CONCURRENT_MODIFICATION",
    "message": (
        "Alguien mas modifico este registro mientras lo editabas. "
        "Actualiza la vista y volve a intentar."
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tipo", "sqlstate"),
    [
        (DBAPIError, "40P01"),
        (OperationalError, "40P01"),
        (DBAPIError, "40001"),
    ],
)
async def test_deadlock_o_serializacion_responde_409_neutro(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tipo: type[DBAPIError],
    sqlstate: str,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, f"deadlock-{sqlstate.lower()}-{tipo.__name__.lower()}")
    error = tipo("SELECT ... FOR UPDATE", {}, _ErrorDelDriver(sqlstate))
    monkeypatch.setattr(PublicBookingService, "book", _que_falle_con(error))

    res = await client.post(
        "/public/appointments", json=_reserva(t, f"deadlock-{sqlstate}-0001")
    )

    assert res.status_code == 409, res.text
    cuerpo = res.json()
    assert {k: cuerpo.get(k) for k in CUERPO_NEUTRO} == CUERPO_NEUTRO
    assert "SELECT" not in res.text and "driver" not in res.text
    assert res.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_otro_error_de_base_sigue_siendo_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "deadlock-otro")
    error = OperationalError("SELECT 1", {}, _ErrorDelDriver("53300"))
    monkeypatch.setattr(PublicBookingService, "book", _que_falle_con(error))

    # El handler generico responde 500 y Starlette vuelve a levantar la
    # excepcion: con raise_app_exceptions=False se ve la respuesta.
    transporte = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transporte,
        base_url="http://test",
        headers={"x-raw-response": "true"},
    ) as sin_reraise:
        res = await sin_reraise.post(
            "/public/appointments", json=_reserva(t, "deadlock-otro-01")
        )

    assert res.status_code == 500, res.text
    assert res.json()["error_code"] == "INTERNAL_SERVER_ERROR"
    assert "SELECT" not in res.text
