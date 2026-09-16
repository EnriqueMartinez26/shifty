"""Anti-acaparamiento de la lista de espera y telefono unico por tienda.

Review 2026-09-11 (MEDIUM): anotarse es anonimo y sin OTP. Un mismo telefono
podia llenar la cola con entradas que nunca reservan y cada cupo liberado
moria en ofertas de 10 minutos a nadie mientras los demas esperaban. Dos topes
deterministas: ``MAX_OPEN_ENTRIES_PER_PHONE`` entradas abiertas por telefono y
tienda, y ``MAX_LAPSED_OFFERS`` ofertas dejadas pasar antes de expirar sola.

Ademas, ``users`` lleva un indice unico parcial (tienda, telefono) para
clientes: dos filas iguales rompian ``get_or_create_client`` con
``MultipleResultsFound`` (500) y la unicidad la garantiza la base, no un
"verificar y luego insertar" en Python.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.payments.jobs import process_outbox_batch
from modules.public_api.repository import _UNUSABLE_CLIENT_PASSWORD_HASH
from modules.users.model import User, UserRole
from modules.waitlist.model import (
    MAX_LAPSED_OFFERS,
    MAX_OPEN_ENTRIES_PER_PHONE,
    WaitlistEntry,
)
from modules.waitlist.offers import expire_lapsed_offers
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_lista_de_espera import _alta, _entrada, _reservar, _tienda
from tests.integration.test_mails_al_cliente import Buzon


async def _liberar(
    client: AsyncClient,
    session: AsyncSession,
    store: str,
    token: str,
    service: str,
    staff: str,
    slot: datetime,
    key: str,
) -> None:
    pid = await _reservar(client, store, service, staff, slot, key)
    res = await client.patch(f"/appointments/{pid}/cancel", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    resultado = await process_outbox_batch(session)
    assert resultado["failed"] == 0


@pytest.mark.asyncio
async def test_un_telefono_no_acumula_mas_entradas_abiertas_que_el_tope(
    client: AsyncClient,
) -> None:
    store, token, service, _staff, slot = await _tienda(client, "acaparar")

    # Ventanas distintas para que no las frene el chequeo de duplicado.
    for i in range(MAX_OPEN_ENTRIES_PER_PHONE):
        res = await client.post(
            "/public/waitlist",
            json=_alta(store, service, slot + timedelta(hours=i)),
        )
        assert res.status_code == 201, res.text

    de_mas = await client.post(
        "/public/waitlist",
        json=_alta(store, service, slot + timedelta(hours=MAX_OPEN_ENTRIES_PER_PHONE)),
    )
    assert de_mas.status_code == 409, de_mas.text
    assert de_mas.json()["error_code"] == "WAITLIST_TOO_MANY_OPEN"

    # Otro telefono no se ve afectado por el tope ajeno.
    otra = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot,
            client_name="Marta Otra",
            client_phone="+5491155550102",
            client_email="marta@example.com",
        ),
    )
    assert otra.status_code == 201, otra.text

    # Cerrar una entrada libera lugar para una nueva.
    listado = await client.get("/waitlist/", headers=auth_headers(token))
    assert listado.status_code == 200, listado.text
    mia = next(e for e in listado.json() if e["client_phone"] == "5491155550101")
    baja = await client.delete(
        f"/waitlist/{mia['public_id']}", headers=auth_headers(token)
    )
    assert baja.status_code == 204, baja.text
    otra_vez = await client.post(
        "/public/waitlist",
        json=_alta(store, service, slot + timedelta(hours=MAX_OPEN_ENTRIES_PER_PHONE)),
    )
    assert otra_vez.status_code == 201, otra_vez.text


@pytest.mark.asyncio
async def test_quien_deja_pasar_dos_ofertas_expira_y_no_bloquea_la_cola(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_LAPSED_OFFERS == 2, "el test cuenta dos ofertas dejadas pasar"
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot_a = await _tienda(client, "ofertas")
    slot_b = slot_a + timedelta(hours=1)

    lucia = await client.post("/public/waitlist", json=_alta(store, service, slot_a))
    marta = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot_a,
            client_name="Marta Segunda",
            client_phone="+5491155550102",
            client_email="marta@example.com",
        ),
    )
    assert lucia.status_code == 201 and marta.status_code == 201
    id_lucia = lucia.json()["public_id"]
    id_marta = marta.json()["public_id"]

    # Cupo A: se le ofrece a Lucia (primera en la cola) y lo deja vencer.
    await _liberar(
        client, test_session, store, token, service, staff, slot_a, "acaparar-000001"
    )
    assert (await _entrada(test_session, id_lucia)).status == "offered"
    t1 = datetime.now(timezone.utc) + timedelta(minutes=30)
    resumen = await expire_lapsed_offers(test_session, now=t1)
    await test_session.commit()
    assert resumen.lapsed == 1 and resumen.reoffered == 1 and resumen.expired == 0
    lucia_row = await _entrada(test_session, id_lucia)
    assert lucia_row.status == "waiting" and lucia_row.lapsed_offers == 1
    # El pase de mano llega a Marta, que tambien lo deja vencer (una vez).
    assert (await _entrada(test_session, id_marta)).status == "offered"
    t2 = t1 + timedelta(minutes=30)
    resumen = await expire_lapsed_offers(test_session, now=t2)
    await test_session.commit()
    assert resumen.lapsed == 1 and resumen.reoffered == 0
    marta_row = await _entrada(test_session, id_marta)
    assert marta_row.status == "waiting" and marta_row.lapsed_offers == 1

    # Cupo B: Lucia sigue primera y lo deja vencer por segunda vez.
    await _liberar(
        client, test_session, store, token, service, staff, slot_b, "acaparar-000002"
    )
    assert (await _entrada(test_session, id_lucia)).status == "offered"
    assert (await _entrada(test_session, id_marta)).status == "waiting"
    t3 = datetime.now(timezone.utc) + timedelta(minutes=30)
    resumen = await expire_lapsed_offers(test_session, now=t3)
    await test_session.commit()

    # Lucia expira sola y el cupo B pasa a Marta en la misma corrida.
    assert resumen.lapsed == 1 and resumen.expired == 1 and resumen.reoffered == 1
    lucia_row = await _entrada(test_session, id_lucia)
    assert lucia_row.status == "expired"
    assert lucia_row.lapsed_offers == MAX_LAPSED_OFFERS
    assert (await _entrada(test_session, id_marta)).status == "offered"
    assert [p.email for p in resumen.pending_emails] == ["marta@example.com"]

    # La expirada ya no cuenta como abierta ni aparece en el panel.
    listado = await client.get("/waitlist/", headers=auth_headers(token))
    assert listado.status_code == 200, listado.text
    assert [e["public_id"] for e in listado.json()] == [id_marta]


@pytest.mark.asyncio
async def test_el_telefono_de_un_cliente_es_unico_por_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_a, _t_a, service_a, _s_a, slot_a = await _tienda(client, "unico-a")
    store_b, _t_b, service_b, _s_b, slot_b = await _tienda(client, "unico-b")

    # El mismo telefono en dos tiendas son dos clientes distintos. (El email
    # va distinto porque ``users.email`` es unico global, no por tienda.)
    assert (
        await client.post("/public/waitlist", json=_alta(store_a, service_a, slot_a))
    ).status_code == 201
    assert (
        await client.post(
            "/public/waitlist",
            json=_alta(store_b, service_b, slot_b, client_email="lucia.b@example.com"),
        )
    ).status_code == 201

    test_session.expire_all()
    entrada = (
        (
            await test_session.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.client_phone == "5491155550101"
                )
            )
        )
        .scalars()
        .first()
    )
    assert entrada is not None
    existente = (
        await test_session.execute(
            select(User).where(
                User.store_id == entrada.store_id,
                User.phone == entrada.client_phone,
                User.role == UserRole.CLIENT,
            )
        )
    ).scalar_one()
    telefono, tienda_id = existente.phone, existente.store_id

    # Un segundo cliente con el mismo telefono en la misma tienda: la base
    # lo rechaza aunque el codigo se olvide de mirar antes de insertar.
    test_session.add(
        User(
            email="otro.tecnico@clientes.noreply",
            hashed_password=_UNUSABLE_CLIENT_PASSWORD_HASH,
            full_name="Impostor",
            phone=telefono,
            role=UserRole.CLIENT,
            store_id=tienda_id,
        )
    )
    with pytest.raises(IntegrityError):
        await test_session.flush()
    await test_session.rollback()

    # El personal si puede compartir el telefono del local con un cliente.
    test_session.add(
        User(
            email="recepcion@example.com",
            hashed_password=_UNUSABLE_CLIENT_PASSWORD_HASH,
            full_name="Recepcion",
            phone=telefono,
            role=UserRole.STAFF,
            store_id=tienda_id,
        )
    )
    await test_session.flush()
    await test_session.rollback()
