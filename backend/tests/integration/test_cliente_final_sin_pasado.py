"""El cliente final nunca reserva en el pasado, aunque la tienda no pida antelacion.

2026-09-25, decision del dueno: la TIENDA puede cargar un horario que ya paso
(alta del panel para un cliente, reservar desde la lista de espera); el
CLIENTE FINAL nunca. Estos tests fijan que los caminos del cliente rechazan
todo inicio en el pasado por si mismos, no por la antelacion minima de la
tienda (``min_booking_notice_hours`` en 0 aca): reservar desde el portal,
reprogramar desde "Mis turnos" y anotarse en la lista de espera. Aceptar una
oferta de la lista de espera no tiene camino propio: el mail lleva al portal y
la reserva es ``POST /public/appointments``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from tests.integration.test_caracterizacion_alta_publica import _reserva
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno


def _hace_un_minuto() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=1)


def _neutro(res: Any) -> None:
    assert res.status_code == 422, res.text
    mensaje = res.json()["message"].lower()
    assert "antelaci" not in mensaje and "hora" not in mensaje, mensaje


@pytest.mark.asyncio
async def test_los_caminos_del_cliente_rechazan_el_pasado_sin_antelacion(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "cliente-sin-pasado")
    await test_session.execute(
        update(Store)
        .where(Store.public_id == t.store)
        .values(min_booking_notice_hours=0)
    )
    await test_session.commit()

    reserva = await client.post(
        "/public/appointments",
        json=_reserva(t, "sin-pasado-reserva", starts_at=_hace_un_minuto().isoformat()),
    )
    reprogramacion = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": _hace_un_minuto().isoformat(),
            "idempotency_key": "sin-pasado-reprogramar",
        },
    )
    lista = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "window_starts_at": (_hace_un_minuto() - timedelta(hours=2)).isoformat(),
            "window_ends_at": _hace_un_minuto().isoformat(),
            "client_name": "Tarde",
            "client_phone": "+5491100007777",
        },
    )

    for res in (reserva, reprogramacion, lista):
        _neutro(res)
