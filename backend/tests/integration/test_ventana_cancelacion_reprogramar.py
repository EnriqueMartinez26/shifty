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

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
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
    clave = "ventana-repro-clave-0001"

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": nuevo_inicio.isoformat(),
            "idempotency_key": clave,
        },
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "CANCELLATION_WINDOW_EXPIRED"
    # El turno original sigue vivo y no se libero el horario: sin esto el
    # cliente esquivaba la politica moviendo el turno en vez de cancelarlo.
    assert (await _turno(test_session, turno)).status == "pending"
    assert await _eventos(test_session) == eventos_antes
    assert await _contar(test_session, Appointment) == turnos_antes
    assert await redis.get(f"idempotency:{clave}") is None


@pytest.mark.asyncio
async def test_reprogramar_fuera_de_la_ventana_sigue_andando(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda nueva no rompe el camino feliz (turno a cinco dias vista)."""
    t, turno = await _con_turno(client, monkeypatch, "ventana-repro-ok")
    nuevo_inicio = t.slot + timedelta(hours=2)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": nuevo_inicio.isoformat(),
            "idempotency_key": "ventana-repro-ok-0001",
        },
    )

    assert res.status_code == 200, res.text
    assert (await _turno(test_session, turno)).status == "cancelled"
    assert (await _turno(test_session, res.json()["public_id"])).status == "pending"


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
