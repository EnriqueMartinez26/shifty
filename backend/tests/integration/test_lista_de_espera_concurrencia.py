"""Invariantes de concurrencia de la lista de espera (revision 2026-09-11).

Hallazgos del review de las Fases 2-5:
- el mail de la oferta salia DENTRO de la transaccion que sostiene el
  ``FOR UPDATE`` del outbox (regla 5): un fallo del lote reenviaba ofertas;
- el consumidor ofrecia sin mirar si el cupo seguia libre ni si ya habia una
  oferta viva sobre el mismo hueco;
- una entrada de la lista podia generar dos turnos desde el panel.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import (
    ReleasedSlot,
    expire_lapsed_offers,
    offer_released_slot,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_lista_de_espera import _alta, _reservar, _tienda
from tests.integration.test_mails_al_cliente import Buzon


def _slot(store_id: str, staff: str, cuando: datetime) -> ReleasedSlot:
    return ReleasedSlot(
        store_id=store_id,
        staff_id=staff,
        starts_at=cuando,
        ends_at=cuando + timedelta(minutes=30),
    )


async def _entrada(session: AsyncSession, entry_id: str) -> WaitlistEntry:
    session.expire_all()
    return (
        await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_el_consumidor_no_manda_el_mail_dentro_de_la_transaccion(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "espera-txn")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text

    pid = await _reservar(client, store, service, staff, slot, "espera-txn-000001")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text

    # offer_released_slot no manda: devuelve el mail pendiente.
    entrada = (await test_session.execute(select(WaitlistEntry))).scalar_one()
    antes = len(buzon.enviados)
    resultado = await offer_released_slot(
        test_session,
        _slot(entrada.store_id, staff, slot),
        now=datetime.now(timezone.utc),
    )
    assert resultado.offered_entry_id == entrada.id
    assert resultado.pending_email is not None
    assert resultado.pending_email.email == "lucia@example.com"
    assert len(buzon.enviados) == antes, "no puede mandar dentro de la transaccion"
    await test_session.rollback()


@pytest.mark.asyncio
async def test_no_se_ofrece_un_cupo_que_volvio_a_ocuparse(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "espera-ocupado")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text

    pid = await _reservar(client, store, service, staff, slot, "espera-ocupado-01")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text

    # Alguien reserva el cupo antes de que corra el consumidor del outbox.
    otra = await _reservar(client, store, service, staff, slot, "espera-ocupado-02")
    assert otra

    await process_outbox_batch(test_session)

    entrada = (await test_session.execute(select(WaitlistEntry))).scalar_one()
    assert entrada.status == "waiting", "el cupo ya no estaba libre"
    avisos = (
        (
            await test_session.execute(
                select(Notification).where(
                    Notification.type == "waitlist.slot_released"
                )
            )
        )
        .scalars()
        .all()
    )
    assert avisos == []


@pytest.mark.asyncio
async def test_dos_eventos_por_el_mismo_hueco_ofrecen_una_sola_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "espera-doble-evento")
    primera = await client.post("/public/waitlist", json=_alta(store, service, slot))
    segunda = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot,
            client_name="Marta",
            client_phone="+5491155550102",
            client_email="marta@example.com",
        ),
    )
    assert primera.status_code == 201 and segunda.status_code == 201

    pid = await _reservar(client, store, service, staff, slot, "espera-doble-evt-01")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text

    entrada = await _entrada(test_session, primera.json()["public_id"])
    ahora = datetime.now(timezone.utc)
    uno = await offer_released_slot(
        test_session, _slot(entrada.store_id, staff, slot), now=ahora
    )
    await test_session.flush()
    dos = await offer_released_slot(
        test_session, _slot(entrada.store_id, staff, slot), now=ahora
    )

    assert uno.offered_entry_id is not None
    assert dos.offered_entry_id is None, "ya habia una oferta viva sobre ese hueco"
    assert (
        await _entrada(test_session, segunda.json()["public_id"])
    ).status == "waiting"


@pytest.mark.asyncio
async def test_la_reoferta_no_vuelve_a_avisarle_al_duenio(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "espera-reoferta")
    primera = await client.post("/public/waitlist", json=_alta(store, service, slot))
    segunda = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot,
            client_name="Marta",
            client_phone="+5491155550102",
            client_email="marta@example.com",
        ),
    )
    assert primera.status_code == 201 and segunda.status_code == 201

    pid = await _reservar(client, store, service, staff, slot, "espera-reoferta-01")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text
    await process_outbox_batch(test_session)

    vencido = datetime.now(timezone.utc) + timedelta(minutes=30)
    resumen = await expire_lapsed_offers(test_session, now=vencido)
    await test_session.commit()
    assert resumen.reoffered == 1

    avisos = (
        (
            await test_session.execute(
                select(Notification).where(
                    Notification.type == "waitlist.slot_released"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1, "el pase de mano no es una novedad para el duenio"


@pytest.mark.asyncio
async def test_una_entrada_no_genera_dos_turnos_desde_el_panel(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "espera-dos-turnos")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text
    entry_id = alta.json()["public_id"]

    primera = await client.post(
        f"/waitlist/{entry_id}/book",
        headers=auth_headers(token),
        json={"starts_at": slot.isoformat(), "staff_id": staff},
    )
    assert primera.status_code == 201, primera.text

    # La misma entrada, otra vez (segunda pestania del panel).
    segunda = await client.post(
        f"/waitlist/{entry_id}/book",
        headers=auth_headers(token),
        json={"starts_at": (slot + timedelta(hours=1)).isoformat(), "staff_id": staff},
    )
    assert segunda.status_code == 404, segunda.text
