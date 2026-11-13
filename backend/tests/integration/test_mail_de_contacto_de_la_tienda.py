"""Mail de contacto de la tienda: el Reply-To de los mails al cliente (#283).

Decision de Mateo (2026-11-02, ultimo comentario del issue): las tiendas no
tenian un email de contacto, asi que se agrega ``stores.contact_email``,
opcional, editable por ``PATCH /stores/me``. Los mails al cliente lo llevan
como ``Reply-To`` (``tests/unit/test_reply_to_de_los_mails_al_cliente.py``
cubre cada tipo de mail); aca se prueban la configuracion y que los caminos
que releen la tienda al mandar (el worker de la reserva publica, el lote del
outbox y la oferta de la lista de espera) leen el contacto de la base.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.payments.jobs import process_outbox_batch
from modules.stores.model import Store
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import ReleasedSlot, offer_released_slot
from tests.integration.pendiente_heredado import como_pendiente_heredado
from tests.integration.test_caracterizacion_alta_publica import _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import (
    _reserva,
    _tienda_reservable,
    usar_cola_de_reservas,
)

CONTACTO = "hola@tienda-del-barrio.com"


async def _contacto_en_la_base(
    session: AsyncSession, store_public_id: str
) -> str | None:
    session.expire_all()
    return (
        await session.execute(
            select(Store.contact_email).where(Store.public_id == store_public_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_la_tienda_carga_normaliza_y_borra_su_mail_de_contacto(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, token = await register_and_login(
        client, slug="contacto-ok", email="contacto-ok@example.com"
    )
    inicial = await client.get("/stores/me", headers=auth_headers(token))
    assert inicial.status_code == 200, inicial.text
    assert inicial.json()["contact_email"] is None

    cargado = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"contact_email": "  Hola@Tienda-Del-Barrio.COM "},
    )
    assert cargado.status_code == 200, cargado.text
    assert cargado.json()["contact_email"] == CONTACTO
    assert await _contacto_en_la_base(test_session, store) == CONTACTO

    vacio = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": ""}
    )
    assert vacio.status_code == 200, vacio.text
    assert vacio.json()["contact_email"] is None
    assert await _contacto_en_la_base(test_session, store) is None

    await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": CONTACTO}
    )
    nulo = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": None}
    )
    assert nulo.status_code == 200, nulo.text
    assert nulo.json()["contact_email"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "valor",
    [
        "no-es-un-mail",
        "hola@",
        f"{CONTACTO}\r\nBcc: espia@example.com",
        "hola​@tienda.com",
        "a" * 250 + "@tienda.com",
        # B1 (verificacion, 2026-11-03): sin forma ASCII no hay Reply-To valido.
        "ñandú@tienda.com",
        "hola@tienda.com>",
    ],
    ids=[
        "sin-arroba",
        "sin-dominio",
        "crlf",
        "zero-width",
        "largo",
        "local-no-ascii",
        "con-angulo",
    ],
)
async def test_un_mail_de_contacto_invalido_da_422_y_no_toca_nada(
    client: AsyncClient, test_session: AsyncSession, valor: str
) -> None:
    store, token = await register_and_login(
        client, slug="contacto-mal", email="contacto-mal@example.com"
    )
    await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": CONTACTO}
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": valor}
    )

    assert res.status_code == 422, res.text
    assert await _contacto_en_la_base(test_session, store) == CONTACTO


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "valor",
    ["hola@bücher.com", "Hola@XN--BCHER-KVA.com"],
    ids=["unicode", "punycode"],
)
async def test_un_dominio_internacional_se_guarda_en_ascii(
    client: AsyncClient, test_session: AsyncSession, valor: str
) -> None:
    """B1 (verificacion, 2026-11-03): un dominio IDN se guarda en punycode.

    EmailStr devolvia la forma Unicode y el sink la mandaba como encoded-word
    dentro de la direccion (RFC 2047 en lugar del dominio): la
    respuesta no llegaba a ningun lado.
    """
    store, token = await register_and_login(
        client, slug="contacto-idn", email="contacto-idn@example.com"
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": valor}
    )

    assert res.status_code == 200, res.text
    assert res.json()["contact_email"] == "hola@xn--bcher-kva.com"
    assert await _contacto_en_la_base(test_session, store) == "hola@xn--bcher-kva.com"


@pytest.mark.asyncio
async def test_el_patch_sin_el_campo_no_toca_el_contacto_ni_lo_demas(
    client: AsyncClient,
) -> None:
    """Comportamiento previo del PATCH: lo que no viaja no se toca."""
    _, token = await register_and_login(
        client, slug="contacto-resto", email="contacto-resto@example.com"
    )
    await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"contact_email": CONTACTO, "description": "Cortes y color"},
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"name": "Nuevo nombre"}
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["name"] == "Nuevo nombre"
    assert cuerpo["contact_email"] == CONTACTO
    assert cuerpo["description"] == "Cortes y color"


@pytest.mark.asyncio
async def test_una_tienda_no_cambia_el_contacto_de_otra(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda_a, token_a = await register_and_login(
        client, slug="contacto-a", email="contacto-a@example.com"
    )
    tienda_b, token_b = await register_and_login(
        client, slug="contacto-b", email="contacto-b@example.com"
    )
    await client.patch(
        "/stores/me", headers=auth_headers(token_b), json={"contact_email": CONTACTO}
    )

    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token_a),
        json={"contact_email": "otra@example.com"},
    )

    assert res.status_code == 200, res.text
    assert await _contacto_en_la_base(test_session, tienda_a) == "otra@example.com"
    assert await _contacto_en_la_base(test_session, tienda_b) == CONTACTO


@pytest.mark.asyncio
async def test_el_portal_publico_no_expone_el_contacto(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="contacto-portal", email="contacto-portal@example.com"
    )
    await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": CONTACTO}
    )

    vitrina = await client.get("/public/stores/contacto-portal")

    assert vitrina.status_code == 200, vitrina.text
    assert CONTACTO not in vitrina.text
    assert "contact_email" not in vitrina.json()


@pytest.fixture
def mensajes(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    capturados: list[EmailMessage] = []

    def _send_sync(self: tasks.SmtpSession, message: EmailMessage) -> None:
        capturados.append(message)

    monkeypatch.setattr(tasks.SmtpSession, "_send_sync", _send_sync)
    return capturados


@pytest.mark.asyncio
async def test_el_worker_y_el_outbox_leen_el_contacto_al_mandar(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    mensajes: list[EmailMessage],
) -> None:
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, token, service, staff, slot = await _tienda_reservable(
        client, "contacto-mails"
    )
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text

    # Se carga DESPUES de encolar: el worker relee la tienda al mandar.
    await client.patch(
        "/stores/me", headers=auth_headers(token), json={"contact_email": CONTACTO}
    )
    assert await cola.entregar() == [{"status": "sent"}]
    [confirmacion] = [m for m in mensajes if m["To"] == "carla@example.com"]
    assert confirmacion["Reply-To"] == CONTACTO

    # El "turno confirmado" del panel sale por el outbox, con el mismo contacto.
    public_id = reserva.json()["public_id"]
    await como_pendiente_heredado(test_session, public_id)
    confirmar = await client.patch(
        f"/appointments/{public_id}/confirm", headers=auth_headers(token)
    )
    assert confirmar.status_code == 200, confirmar.text
    await process_outbox_batch(test_session)
    al_cliente = [m for m in mensajes if m["To"] == "carla@example.com"]
    assert len(al_cliente) == 2
    assert al_cliente[1]["Reply-To"] == CONTACTO
    # El aviso al dueno del mismo lote no lleva la cabecera.
    al_dueno = [m for m in mensajes if m["To"] != "carla@example.com"]
    assert al_dueno and all("Reply-To" not in m for m in al_dueno)


@pytest.mark.asyncio
async def test_sin_contacto_el_worker_no_pone_reply_to(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    mensajes: list[EmailMessage],
) -> None:
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, _token, service, staff, slot = await _tienda_reservable(
        client, "contacto-sin"
    )
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text

    assert await cola.entregar() == [{"status": "sent"}]
    [confirmacion] = mensajes
    assert "Reply-To" not in confirmacion


@pytest.mark.asyncio
async def test_la_oferta_de_la_lista_de_espera_lee_el_contacto(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "contacto-espera")
    await client.patch(
        "/stores/me", headers=auth_headers(t.token), json={"contact_email": CONTACTO}
    )
    alta = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "window_starts_at": (t.slot - timedelta(hours=2)).isoformat(),
            "window_ends_at": (t.slot + timedelta(hours=2)).isoformat(),
            "client_name": "Marta",
            "client_phone": "+5491155559201",
            "client_email": "marta@example.com",
        },
    )
    assert alta.status_code == 201, alta.text
    entrada = (await test_session.execute(select(WaitlistEntry))).scalars().one()
    hueco = ReleasedSlot(
        store_id=entrada.store_id,
        staff_id=t.staff,
        starts_at=t.slot,
        ends_at=t.slot + timedelta(minutes=30),
        reason="cancelled",
    )

    oferta = await offer_released_slot(
        test_session, hueco, now=datetime.now(timezone.utc)
    )

    assert oferta.pending_email is not None
    assert oferta.pending_email.details["reply_to"] == CONTACTO
