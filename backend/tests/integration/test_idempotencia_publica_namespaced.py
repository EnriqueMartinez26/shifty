"""La clave de idempotencia del portal no es un identificador global.

Auditoria 2, AUD2-B1-06 (2026-09-20). Sintoma: `PublicBookingCreate.
idempotency_key` es texto libre (10 a 128 caracteres, sin patron) y el router
la usaba TAL CUAL como clave global de Redis (`idempotency:{key}`), sin
tienda ni telefono adentro. La respuesta exitosa se cachea 24 horas y
`idempotency_guard` se la devolvia a cualquiera que mandara la misma cadena:
`client_name`, `client_phone`, `notes`, `custom_fields`, `payment_link` y el
`public_id` del turno ajeno. Y si el cliente no mandaba clave, la derivada es
sha256 de `service_id|staff_id|starts_at|client_phone`, o sea reconstruible
por quien conozca esos cuatro datos de la victima.

Es un endpoint ANONIMO: el resto del sistema protege esos mismos datos con
OTP. Ahora la clave que viaja a Redis se namespacea siempre por tienda,
servicio y telefono, asi que sigue siendo estable para el reintento del mismo
cliente y deja de ser adivinable desde afuera.

La reprogramacion del portal tenia el mismo defecto en el mismo archivo y con
la misma respuesta (`PublicBookingResponse`), y ahi ademas el replay cacheado
contesta ANTES de la guarda de telefono y de OTP: se arregla junto, con la
clave namespaceada por turno y telefono.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from modules.public_api.router import _public_booking_idempotency_key
from modules.public_api.schemas import PublicBookingCreate
from tests.integration.test_caracterizacion_alta_publica import (
    _redis,
    _reserva,
    _tienda,
)
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno
from tests.integration.test_mails_al_cliente import Buzon

CLAVE = "clave-compartida-01"


@pytest.mark.asyncio
async def test_la_clave_de_otro_no_devuelve_su_reserva(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "idem-namespace")
    victima = await client.post("/public/appointments", json=_reserva(t, CLAVE))
    assert victima.status_code == 201, victima.text
    datos_victima = victima.json()

    # Mismo texto de clave, otra persona, otro horario: el atacante solo
    # necesita adivinar (o ver) la cadena.
    atacante = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            CLAVE,
            starts_at=(t.slot + timedelta(hours=3)).isoformat(),
            client_name="Atacante",
            client_phone="+5491155559999",
            client_email="atacante@example.com",
            notes=None,
        ),
    )

    cuerpo = atacante.json()
    assert cuerpo.get("client_name") != datos_victima["client_name"], cuerpo
    assert cuerpo.get("client_phone") != datos_victima["client_phone"], cuerpo
    assert cuerpo.get("public_id") != datos_victima["public_id"], cuerpo
    assert cuerpo.get("notes") != datos_victima["notes"], cuerpo
    # Lo que ve el atacante: el 409 neutro del unico de
    # `appointments.idempotency_key`, que sigue siendo la ultima defensa.
    assert atacante.status_code == 409, atacante.text
    assert cuerpo["error_code"] == "RESOURCE_CONFLICT"


@pytest.mark.asyncio
async def test_la_clave_derivada_de_la_victima_tampoco_sirve(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin clave propia, la derivada la puede reconstruir quien sepa los datos."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "idem-derivada")
    sin_clave = _reserva(t, "descartada")
    del sin_clave["idempotency_key"]
    victima = await client.post("/public/appointments", json=sin_clave)
    assert victima.status_code == 201, victima.text

    # Reconstruida desde afuera con los cuatro datos de la victima.
    derivada = _public_booking_idempotency_key(PublicBookingCreate(**sin_clave))
    assert derivada.startswith("public-"), derivada

    atacante = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            "reemplazada",
            starts_at=(t.slot + timedelta(hours=3)).isoformat(),
            client_name="Atacante",
            client_phone="+5491155559998",
            client_email="atacante2@example.com",
            idempotency_key=derivada,
        ),
    )

    cuerpo = atacante.json()
    assert cuerpo.get("client_phone") != victima.json()["client_phone"], cuerpo
    assert cuerpo.get("public_id") != victima.json()["public_id"], cuerpo
    assert atacante.status_code == 409, atacante.text


@pytest.mark.asyncio
async def test_el_reintento_del_mismo_cliente_sigue_siendo_idempotente(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Para lo que la clave existe: el mismo cuerpo repetido no duplica nada."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "idem-replay")
    cuerpo = _reserva(t, "replay-mismo-cliente")

    primera = await client.post("/public/appointments", json=cuerpo)
    segunda = await client.post("/public/appointments", json=cuerpo)

    assert primera.status_code == 201, primera.text
    assert segunda.status_code == 201, segunda.text
    assert segunda.json() == primera.json()
    # La cadena cruda del cliente ya no es la clave de Redis.
    redis = await _redis()
    assert await redis.get("idempotency:replay-mismo-cliente") is None


@pytest.mark.asyncio
async def test_la_clave_de_reprogramar_no_saltea_la_guarda_de_telefono(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El replay cacheado contesta antes de mirar de quien es el turno."""
    t, turno = await _con_turno(client, monkeypatch, "idem-repro")
    pedido = {
        "phone": TELEFONO,
        "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
        "idempotency_key": CLAVE,
    }
    victima = await client.patch(
        f"/public/client/appointments/{turno}/reschedule", json=pedido
    )
    assert victima.status_code == 200, victima.text

    # Mismo turno y misma clave, otro telefono y sin OTP verificado.
    atacante = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={**pedido, "phone": "+5491155559997"},
    )

    cuerpo = atacante.json()
    assert cuerpo.get("client_phone") != victima.json()["client_phone"], cuerpo
    assert cuerpo.get("public_id") != victima.json()["public_id"], cuerpo
    assert atacante.status_code == 403, atacante.text
    assert cuerpo["error_code"] == "PERMISSION_DENIED"
