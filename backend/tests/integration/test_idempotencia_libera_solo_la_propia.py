"""El `except` del portal no libera la idempotencia de OTRA peticion en vuelo.

Auditoria 2, AUD2-B1-07 (2026-09-20). Sintoma: en los dos handlers publicos
la llamada a `idempotency_guard` estaba ADENTRO del `try` y el `except` hacia
`idempotency_release` sin mirar que fallo. Si la guarda espero
`MAX_WAIT_SECONDS` porque otra peticion con la misma clave seguia corriendo y
levanto `IdempotencyInProgressException`, este handler borraba el marcador
`PROCESSING` de ESA otra peticion: una tercera peticion simultanea lo tomaba y
entraba al alta en paralelo. Es justo lo contrario de lo que la guarda debe
hacer bajo rafaga (regla 6 y §4 de CLAUDE.md). La ultima defensa (el unico de
`appointments.idempotency_key` y la exclusion GiST) evitaba el turno
duplicado, pero convertia una rafaga de 1x201 + N-1x409 limpios en errores de
base.

Aca la peticion en vuelo se simula dejando el marcador `PROCESSING` puesto en
Redis: es el mismo estado que deja `idempotency_guard` al adquirir la clave, y
sin reloj de por medio el caso es deterministico. La rafaga real (N peticiones
concurrentes con la misma clave) vive en
`tests/postgres/test_pg_rafaga_idempotencia_publica.py`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

import core.idempotency as idempotency
import modules.notifications.tasks as tasks
from modules.public_api.router import _booking_cache_key, _reschedule_cache_key
from modules.public_api.schemas import ClientRescheduleRequest, PublicBookingCreate
from tests.integration.test_caracterizacion_alta_publica import (
    _redis,
    _reserva,
    _tienda,
)
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno
from tests.integration.test_mails_al_cliente import Buzon


@pytest.fixture(autouse=True)
def _sin_espera(monkeypatch: pytest.MonkeyPatch) -> None:
    """La guarda se rinde enseguida: interesa que pasa DESPUES del timeout."""
    monkeypatch.setattr(idempotency, "MAX_WAIT_SECONDS", 0.0)


@pytest.mark.asyncio
async def test_el_alta_no_borra_el_marcador_de_otra_peticion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "release-alta")
    cuerpo = _reserva(t, "release-alta-0001")
    clave = "idempotency:" + _booking_cache_key(
        PublicBookingCreate(**cuerpo), str(cuerpo["idempotency_key"])
    )
    redis = await _redis()
    # Otra peticion con la misma clave ya esta adentro del alta.
    await redis.set(clave, idempotency.PROCESSING_VALUE)

    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
    # El marcador de la otra peticion sigue en pie: una tercera no entra.
    assert await redis.get(clave) == idempotency.PROCESSING_VALUE


@pytest.mark.asyncio
async def test_reprogramar_no_borra_el_marcador_de_otra_peticion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "release-repro")
    pedido: dict[str, Any] = {
        "phone": TELEFONO,
        "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
        "idempotency_key": "release-repro-0001",
    }
    clave = "idempotency:" + _reschedule_cache_key(
        turno, ClientRescheduleRequest(**pedido)
    )
    redis = await _redis()
    await redis.set(clave, idempotency.PROCESSING_VALUE)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule", json=pedido
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert await redis.get(clave) == idempotency.PROCESSING_VALUE


@pytest.mark.asyncio
async def test_la_peticion_que_si_adquirio_la_clave_la_sigue_liberando(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda que si protege: un fallo propio no deja la clave trabada."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "release-propia")
    primera = await client.post(
        "/public/appointments", json=_reserva(t, "release-propia-0001")
    )
    assert primera.status_code == 201, primera.text

    # Mismo slot, otro cliente: el alta falla con 409 y libera SU clave.
    cuerpo = _reserva(
        t,
        "release-propia-0002",
        client_phone="+5491155557777",
        client_email="otro-release@example.com",
    )
    segunda = await client.post("/public/appointments", json=cuerpo)

    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["error_code"] == "APPOINTMENT_CONFLICT"
    clave = "idempotency:" + _booking_cache_key(
        PublicBookingCreate(**cuerpo), str(cuerpo["idempotency_key"])
    )
    redis = await _redis()
    assert await redis.get(clave) is None
