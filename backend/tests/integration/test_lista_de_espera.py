"""Lista de espera con relleno (Fase 4, 2026-09-10).

Anotarse, duplicado rechazado, cada camino que libera un cupo publica el
evento, el consumidor le ofrece a UNA persona por vez, la oferta vence y pasa
a la siguiente, los cupos dentro de la antelacion minima no se mailean y el
dueno reserva a mano desde el panel.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from modules.waitlist.events import EVENT_SLOT_RELEASED
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import expire_lapsed_offers
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


async def _tienda(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    return store, token, service, staff, slot


def _alta(
    store: str, service: str, slot: datetime, **extra: object
) -> dict[str, object]:
    cuerpo: dict[str, object] = {
        "store_public_id": store,
        "service_id": service,
        "window_starts_at": (slot - timedelta(hours=3)).isoformat(),
        "window_ends_at": (slot + timedelta(hours=3)).isoformat(),
        "client_name": "Lucia Espera",
        "client_phone": "+5491155550101",
        "client_email": "lucia@example.com",
    }
    cuerpo.update(extra)
    return cuerpo


async def _reservar(
    client: AsyncClient, store: str, service: str, staff: str, slot: datetime, key: str
) -> str:
    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Titular",
            "client_phone": "+5491155550200",
            "client_email": "titular@example.com",
            "idempotency_key": key,
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _eventos(session: AsyncSession) -> list[OutboxMessage]:
    rows = await session.execute(
        select(OutboxMessage).where(OutboxMessage.event_type == EVENT_SLOT_RELEASED)
    )
    return list(rows.scalars().all())


async def _entrada(session: AsyncSession, entry_id: str) -> WaitlistEntry:
    session.expire_all()
    return (
        await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_anotarse_y_duplicado_rechazado(client: AsyncClient) -> None:
    store, token, service, staff, slot = await _tienda(client, "espera")

    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text
    assert alta.json()["status"] == "waiting"
    assert alta.json()["service_id"] == service
    assert alta.json()["staff_id"] is None

    repetido = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert repetido.status_code == 409, repetido.text
    assert repetido.json()["error_code"] == "WAITLIST_DUPLICATE"

    otro_profesional = await client.post(
        "/public/waitlist", json=_alta(store, service, slot, staff_id="no-existe")
    )
    assert otro_profesional.status_code == 404, otro_profesional.text

    listado = await client.get("/waitlist/", headers=auth_headers(token))
    assert listado.status_code == 200, listado.text
    assert len(listado.json()) == 1
    assert listado.json()[0]["client_phone"] == "5491155550101"


@pytest.mark.asyncio
async def test_cada_camino_que_libera_un_cupo_publica_el_evento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "caminos")

    # 1. Cancelar desde el panel.
    pid = await _reservar(client, store, service, staff, slot, "caminos-000001")
    res = await client.patch(f"/appointments/{pid}/cancel", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    assert len(await _eventos(test_session)) == 1

    # 2. Liberar un pendiente.
    pid = await _reservar(client, store, service, staff, slot, "caminos-000002")
    res = await client.patch(
        f"/appointments/{pid}/release", headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    assert len(await _eventos(test_session)) == 2

    # 3. Reprogramar desde el panel (libera el original).
    pid = await _reservar(client, store, service, staff, slot, "caminos-000003")
    res = await client.patch(
        f"/appointments/{pid}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": (slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "caminos-reschedule-000001",
        },
    )
    assert res.status_code == 200, res.text
    assert len(await _eventos(test_session)) == 3

    # 4. Borrar un bloqueo.
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": (slot + timedelta(days=1)).isoformat(),
            "ends_at": (slot + timedelta(days=1, hours=1)).isoformat(),
            "reason": "Vacaciones",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    res = await client.delete(
        f"/appointment-blocks/{bloqueo.json()['public_id']}",
        headers=auth_headers(token),
    )
    assert res.status_code == 204, res.text
    eventos = await _eventos(test_session)
    assert len(eventos) == 4
    assert {e.payload["reason"] for e in eventos} == {
        "cancelled",
        "released",
        "rescheduled",
        "block_deleted",
    }


@pytest.mark.asyncio
async def test_el_cupo_se_ofrece_a_una_sola_persona_y_pasa_a_la_siguiente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "oferta")

    primera = await client.post("/public/waitlist", json=_alta(store, service, slot))
    segunda = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot,
            client_name="Marta Segunda",
            client_phone="+5491155550102",
            client_email="marta@example.com",
        ),
    )
    assert primera.status_code == 201 and segunda.status_code == 201
    id_primera = primera.json()["public_id"]
    id_segunda = segunda.json()["public_id"]

    pid = await _reservar(client, store, service, staff, slot, "oferta-000001")
    res = await client.patch(f"/appointments/{pid}/cancel", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    mails_antes = len(buzon.enviados)

    resultado = await process_outbox_batch(test_session)
    assert resultado["failed"] == 0

    # Solo la primera recibe la oferta; la segunda sigue esperando.
    ofrecida = await _entrada(test_session, id_primera)
    assert ofrecida.status == "offered"
    assert ofrecida.offer_expires_at is not None
    assert (await _entrada(test_session, id_segunda)).status == "waiting"
    nuevos = buzon.enviados[mails_antes:]
    oferta = next(e for e in nuevos if e[1].startswith("Se libero un turno"))
    assert oferta[0] == "lucia@example.com"
    assert f"/b/oferta?service={service}&staff={staff}&date=" in oferta[2]
    assert all(e[0] != "marta@example.com" for e in nuevos)

    # El dueno recibe la notificacion in-app con la cantidad de anotados.
    aviso = (
        await test_session.execute(
            select(Notification).where(Notification.type == "waitlist.slot_released")
        )
    ).scalar_one()
    assert "2 en lista de espera" in (aviso.body or "")

    # Vence la ventana sin reservar: la oferta pasa a la segunda.
    vencido = datetime.now(timezone.utc) + timedelta(minutes=30)
    resumen = await expire_lapsed_offers(test_session, now=vencido)
    await test_session.commit()
    assert resumen.lapsed == 1 and resumen.reoffered == 1
    assert (await _entrada(test_session, id_primera)).status == "waiting"
    assert (await _entrada(test_session, id_segunda)).status == "offered"
    # El mail vuelve pendiente: se manda FUERA de la transaccion (regla 5).
    assert [p.email for p in resumen.pending_emails] == ["marta@example.com"]
    for pendiente in resumen.pending_emails:
        await tasks.enqueue_waitlist_offer_email(
            email=pendiente.email, details=pendiente.details
        )
    assert any(e[0] == "marta@example.com" for e in buzon.enviados)

    # Marta reserva el cupo: su entrada se cierra sola.
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Marta Segunda",
            "client_phone": "+5491155550102",
            "client_email": "marta@example.com",
            "idempotency_key": "oferta-marta-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert (await _entrada(test_session, id_segunda)).status == "booked"


@pytest.mark.asyncio
async def test_un_cupo_dentro_de_la_antelacion_minima_no_se_mailea(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, _token, service, staff, slot = await _tienda(client, "pronto")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text
    entry_id = alta.json()["public_id"]

    # El consumidor corre "una hora antes del turno": el cliente ya no puede
    # reservar por el portal (antelacion minima de 2h), asi que solo se le
    # avisa al dueno y la entrada sigue esperando.
    from modules.waitlist.offers import ReleasedSlot, offer_released_slot

    entrada = await _entrada(test_session, entry_id)
    resultado = await offer_released_slot(
        test_session,
        ReleasedSlot(
            store_id=entrada.store_id,
            staff_id=staff,
            starts_at=slot,
            ends_at=slot + timedelta(minutes=30),
        ),
        now=slot - timedelta(hours=1),
    )
    await test_session.commit()

    assert resultado.candidates == 1
    assert resultado.owner_notified is True
    assert resultado.offered_entry_id is None
    assert (await _entrada(test_session, entry_id)).status == "waiting"
    assert not any(e[1].startswith("Se libero un turno") for e in buzon.enviados)
    aviso = (
        await test_session.execute(
            select(Notification).where(Notification.type == "waitlist.slot_released")
        )
    ).scalar_one()
    assert "1 en lista de espera" in (aviso.body or "")


@pytest.mark.asyncio
async def test_el_dueno_reserva_a_mano_desde_la_lista(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "amano")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text
    entry_id = alta.json()["public_id"]

    reserva = await client.post(
        f"/waitlist/{entry_id}/book",
        headers=auth_headers(token),
        json={"starts_at": slot.isoformat(), "staff_id": staff},
    )
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["status"] == "confirmed"
    assert any(e[1].startswith("Turno confirmado") for e in buzon.enviados)

    listado = await client.get("/waitlist/", headers=auth_headers(token))
    assert listado.json() == []

    # El mismo horario ya no se puede volver a dar.
    otra = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert otra.status_code == 201
    choque = await client.post(
        f"/waitlist/{otra.json()['public_id']}/book",
        headers=auth_headers(token),
        json={"starts_at": slot.isoformat(), "staff_id": staff},
    )
    assert choque.status_code == 409, choque.text
