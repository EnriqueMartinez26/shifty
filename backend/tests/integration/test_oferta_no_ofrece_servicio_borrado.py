"""La lista de espera no ofrece un cupo de un servicio dado de baja.

Auditoria 2 (catalogo, 2026-09-20). ``matching_entries`` unia ``Service`` sin
mirar ``is_active``, asi que un servicio borrado (baja logica:
``ServiceRepository.soft_delete``) seguia generando ofertas. El cliente
recibia el mail "Se libero un turno", entraba al portal y el alta le
respondia 404 (``get_service_by_public_id`` exige ``Service.is_active``):
encima la oferta vencia sola y le gastaba una de las ``MAX_LAPSED_OFFERS``
que tiene antes de que su entrada expire.

Ahora la entrada de un servicio inactivo no encaja con ningun hueco: se
queda esperando sin que le quemen ofertas (si el duenio revive el servicio,
vuelve a entrar en la rueda).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.payments.jobs import process_outbox_batch
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_lista_de_espera import _alta, _entrada, _reservar, _tienda
from tests.integration.test_mails_al_cliente import Buzon


@pytest.mark.asyncio
async def test_un_servicio_borrado_no_genera_ofertas(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "servicio-baja")
    anotado = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert anotado.status_code == 201, anotado.text
    entrada = anotado.json()["public_id"]

    turno = await _reservar(client, store, service, staff, slot, "baja-000001")
    baja = await client.delete(f"/services/{service}", headers=auth_headers(token))
    assert baja.status_code == 204, baja.text
    # El cupo se libera igual: el turno ya reservado se puede cancelar.
    cancelado = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(token)
    )
    assert cancelado.status_code == 200, cancelado.text
    mails_antes = len(buzon.enviados)

    resultado = await process_outbox_batch(test_session)

    assert resultado["failed"] == 0
    assert (await _entrada(test_session, entrada)).status == "waiting"
    assert (await _entrada(test_session, entrada)).lapsed_offers == 0
    nuevos = buzon.enviados[mails_antes:]
    assert not [e for e in nuevos if e[1].startswith("Se libero un turno")]

    # Por que importaba: ese mail llevaba a un alta que responde 404.
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Lucia Espera",
            "client_phone": "+5491155550101",
            "accepts_terms": True,
            "client_email": "lucia@example.com",
            "idempotency_key": "baja-reserva-0001",
        },
    )
    assert reserva.status_code == 404, reserva.text
