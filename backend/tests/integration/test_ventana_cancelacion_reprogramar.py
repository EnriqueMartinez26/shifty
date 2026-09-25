"""La ventana de cancelacion de la tienda tambien rige para reprogramar.

Auditoria 2, AUD2-B1-02 (2026-09-20). Sintoma: `cancel_by_client` aplicaba
`cancellation_hours` y `reschedule_by_client` no. Como reprogramar CANCELA el
turno original, un cliente al que ya se le paso la ventana (faltan 30
minutos, la tienda pide 2 horas) movia el turno a una fecha lejana y liberaba
el horario igual: la politica de la tienda era inaplicable desde el portal.
Encima el listado de "mis turnos" publica `can_reschedule = can_cancel`, asi
que el front lo ocultaba y la API lo permitia.

Decision del duenio (2026-09-20): la ventana aplica a los dos caminos.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.public_api.router import _reschedule_cache_key
from modules.public_api.schemas import ClientRescheduleRequest
from tests.integration.test_caracterizacion_alta_publica import (
    _contar,
    _eventos,
    _redis,
)
from tests.integration.test_caracterizacion_autogestion import (
    TELEFONO,
    _con_turno,
    _turno,
)


async def _adelantar(session: AsyncSession, turno: str, minutos: int) -> datetime:
    """Deja el turno a `minutos` vista, dentro de la ventana de la tienda."""
    inicio = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    await session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(starts_at=inicio, ends_at=inicio + timedelta(minutes=30))
    )
    await session.commit()
    return inicio


def _clave_redis(turno: str, cuerpo: dict[str, Any]) -> str:
    """La clave real que la reprogramacion usa en Redis (AUD2-B1-06).

    Es la namespaceada por turno y telefono, no la cadena cruda del cliente:
    afirmar sobre ``idempotency:{clave cruda}`` daba siempre ``None`` y la
    asercion de liberacion no probaba nada (AUD2-POST-04).
    """
    return "idempotency:" + _reschedule_cache_key(
        turno, ClientRescheduleRequest(**cuerpo)
    )


@pytest.mark.asyncio
async def test_reprogramar_dentro_de_la_ventana_se_rechaza(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "ventana-repro")
    await _adelantar(test_session, turno, 30)
    nuevo_inicio = t.slot + timedelta(hours=2)
    eventos_antes = await _eventos(test_session)
    turnos_antes = await _contar(test_session, Appointment)
    redis = await _redis()
    cuerpo: dict[str, Any] = {
        "phone": TELEFONO,
        "new_starts_at": nuevo_inicio.isoformat(),
        "idempotency_key": "ventana-repro-clave-0001",
    }

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule", json=cuerpo
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "CANCELLATION_WINDOW_EXPIRED"
    # El turno original sigue vivo y no se libero el horario: sin esto el
    # cliente esquivaba la politica moviendo el turno en vez de cancelarlo.
    assert (await _turno(test_session, turno)).status == "pending"
    assert await _eventos(test_session) == eventos_antes
    assert await _contar(test_session, Appointment) == turnos_antes
    # El rechazo libero la clave que ESTA peticion adquirio: un reintento del
    # cliente vuelve a evaluarse en vez de recibir el 409 cacheado.
    assert await redis.get(_clave_redis(turno, cuerpo)) is None


@pytest.mark.asyncio
async def test_reprogramar_fuera_de_la_ventana_sigue_andando(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda nueva no rompe el camino feliz (turno a cinco dias vista)."""
    t, turno = await _con_turno(client, monkeypatch, "ventana-repro-ok")
    nuevo_inicio = t.slot + timedelta(hours=2)
    redis = await _redis()
    cuerpo: dict[str, Any] = {
        "phone": TELEFONO,
        "new_starts_at": nuevo_inicio.isoformat(),
        "idempotency_key": "ventana-repro-ok-0001",
    }

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule", json=cuerpo
    )

    assert res.status_code == 200, res.text
    assert (await _turno(test_session, turno)).status == "cancelled"
    assert (await _turno(test_session, res.json()["public_id"])).status == "pending"
    # Con exito, la MISMA clave derivada queda guardada con la respuesta: es
    # la prueba de que ``_clave_redis`` apunta a lo que el router escribe y
    # de que el ``None`` del test de rechazo significa "liberada", no
    # "nunca existio".
    guardado = await redis.get(_clave_redis(turno, cuerpo))
    assert guardado is not None
    if isinstance(guardado, bytes):
        guardado = guardado.decode("utf-8")
    assert json.loads(guardado)["public_id"] == res.json()["public_id"]


@pytest.mark.asyncio
async def test_mis_turnos_y_la_api_dicen_lo_mismo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`can_reschedule` del listado ya no miente: la API rechaza lo mismo."""
    t, turno = await _con_turno(client, monkeypatch, "ventana-repro-listado")
    await _adelantar(test_session, turno, 30)

    listado = await client.get(f"/public/client/{t.store}/{TELEFONO}/appointments")

    assert listado.status_code == 200, listado.text
    item = next(i for i in listado.json()["appointments"] if i["public_id"] == turno)
    assert (item["can_cancel"], item["can_reschedule"]) == (False, False)
    rechazo = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "ventana-repro-listado-01",
        },
    )
    assert rechazo.status_code == 409, rechazo.text
    assert rechazo.json()["error_code"] == "CANCELLATION_WINDOW_EXPIRED"
    assert (
        await test_session.scalar(
            select(Appointment.status).where(Appointment.id == turno)
        )
        == "pending"
    )
