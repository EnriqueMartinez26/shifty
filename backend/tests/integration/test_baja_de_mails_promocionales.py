"""Baja del mail promocional "volve a reservar" (Ley 25.326 art. 27; L3-05, L1 O-8).

2026-09-25. El mail "Gracias por tu visita / Reserva tu proximo turno" invita
a volver a comprar y no ofrecia forma de darse de baja: el unico interruptor
era de la tienda. Ahora:

- el mail lleva un link firmado (HMAC con clave derivada de ``SECRET_KEY``) y
  con vencimiento, por cliente y tienda;
- ``GET /public/unsubscribe`` con el ``token`` del link registra la baja
  (``marketing_opt_outs``) y responde una confirmacion neutra; es idempotente
  y un link adulterado o vencido es 400 sin tocar nada;
- con la baja, ese mail no sale mas. Los transaccionales (registro,
  confirmacion, recordatorios, cancelaciones) siguen igual.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment
from modules.legal.model import MarketingOptOut
from modules.legal.unsubscribe import (
    make_unsubscribe_token,
    read_unsubscribe_token,
)
from modules.payments.jobs import process_outbox_batch
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon, _reserva, _tienda_reservable

AHORA = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def test_el_token_se_firma_y_se_lee() -> None:
    token = make_unsubscribe_token("tienda-1", "cliente-1", now=AHORA)
    assert read_unsubscribe_token(token, now=AHORA) == ("tienda-1", "cliente-1")
    assert "tienda-1" not in token.split(".")[-1]


@pytest.mark.parametrize(
    "adulterar",
    [
        lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
        lambda t: t.replace("cliente-1", "cliente-2"),
        lambda t: t.replace("tienda-1", "tienda-2"),
        lambda t: "basura",
        lambda t: "",
    ],
)
def test_un_token_adulterado_no_vale(adulterar: object) -> None:
    token = make_unsubscribe_token("tienda-1", "cliente-1", now=AHORA)
    assert callable(adulterar)
    assert read_unsubscribe_token(adulterar(token), now=AHORA) is None


def test_un_token_vencido_no_vale() -> None:
    token = make_unsubscribe_token("tienda-1", "cliente-1", now=AHORA)
    assert read_unsubscribe_token(token, now=AHORA + timedelta(days=89)) is not None
    assert read_unsubscribe_token(token, now=AHORA + timedelta(days=91)) is None


async def _turno(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, str, Appointment]:
    store, token, service, staff, slot = await _tienda_reservable(client, slug)
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="carla@example.com"),
    )
    assert reserva.status_code == 201, reserva.text
    pid = str(reserva.json()["public_id"])
    turno = (
        await test_session.execute(select(Appointment).where(Appointment.id == pid))
    ).scalar_one()
    assert turno.client_id is not None
    return token, pid, turno


async def _bajas(test_session: AsyncSession) -> list[MarketingOptOut]:
    test_session.expire_all()
    return list((await test_session.execute(select(MarketingOptOut))).scalars())


@pytest.mark.asyncio
async def test_la_baja_es_idempotente_y_neutra(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _token, _pid, turno = await _turno(client, test_session, "baja-idem")
    tienda, cliente = turno.store_id, str(turno.client_id)
    link = make_unsubscribe_token(tienda, cliente)

    primera = await client.get("/public/unsubscribe", params={"token": link})
    segunda = await client.get("/public/unsubscribe", params={"token": link})

    assert primera.status_code == 200, primera.text
    assert primera.json() == segunda.json() == {"status": "unsubscribed"}
    [baja] = await _bajas(test_session)
    assert baja.client_id == cliente and baja.store_id == tienda
    assert baja.opted_out_at is not None


@pytest.mark.asyncio
async def test_un_link_adulterado_o_vencido_no_da_de_baja(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _token, _pid, turno = await _turno(client, test_session, "baja-mala")
    vencido = make_unsubscribe_token(
        turno.store_id,
        str(turno.client_id),
        now=datetime.now(timezone.utc) - timedelta(days=120),
    )
    valido = make_unsubscribe_token(turno.store_id, str(turno.client_id))

    for token in (vencido, valido[:-3] + "xyz", "a.b.c"):
        res = await client.get("/public/unsubscribe", params={"token": token})
        assert res.status_code == 400, res.text
        assert res.json()["error_code"] == "UNSUBSCRIBE_LINK_INVALID"
    assert await _bajas(test_session) == []


@pytest.mark.asyncio
async def test_con_la_baja_no_sale_el_mail_de_volver_pero_si_los_transaccionales(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    token, pid, turno = await _turno(client, test_session, "baja-envio")
    res = await client.get(
        "/public/unsubscribe",
        params={"token": make_unsubscribe_token(turno.store_id, str(turno.client_id))},
    )
    assert res.status_code == 200, res.text

    confirmar = await client.patch(
        f"/appointments/{pid}/confirm", headers=auth_headers(token)
    )
    assert confirmar.status_code == 200, confirmar.text
    await process_outbox_batch(test_session)
    completar = await client.patch(
        f"/appointments/{pid}/complete", headers=auth_headers(token)
    )
    assert completar.status_code == 200, completar.text
    await process_outbox_batch(test_session)

    asuntos = [asunto for _to, asunto, _cuerpo in buzon.enviados]
    assert any(a.startswith("Turno confirmado") for a in asuntos), asuntos
    assert not any(a.startswith("Gracias por tu visita") for a in asuntos), asuntos


@pytest.mark.asyncio
async def test_el_mail_de_volver_trae_el_link_de_baja_que_funciona(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    token, pid, _turno_ = await _turno(client, test_session, "baja-link")
    for accion in ("confirm", "complete"):
        res = await client.patch(
            f"/appointments/{pid}/{accion}", headers=auth_headers(token)
        )
        assert res.status_code == 200, res.text
    await process_outbox_batch(test_session)

    [cuerpo] = [
        c for _t, a, c in buzon.enviados if a.startswith("Gracias por tu visita")
    ]
    assert "darte de baja" in cuerpo
    link = next(
        palabra for palabra in cuerpo.split() if "/public/unsubscribe" in palabra
    )
    res = await client.get(
        "/public/unsubscribe", params={"token": link.split("token=", 1)[1]}
    )
    assert res.status_code == 200, res.text
    assert len(await _bajas(test_session)) == 1


@pytest.mark.parametrize(
    "token",
    ["a.b.1.é", "é.b.1.firma", "a.b.1.", "", "a" * 300, "a.b.c.d." * 40],
)
def test_un_token_no_ascii_vacio_o_enorme_no_vale(token: str) -> None:
    """Revision de fix/legal-datos (2026-09-25): ``hmac.compare_digest`` sobre
    ``str`` levanta ``TypeError`` con una firma no ASCII (500 anonimo)."""
    assert read_unsubscribe_token(token, now=AHORA) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["a.b.1.é", "éé.b.1.x", "x" * 256])
async def test_la_api_responde_400_y_no_500_con_un_token_raro(
    client: AsyncClient, token: str
) -> None:
    res = await client.get("/public/unsubscribe", params={"token": token})
    assert res.status_code == 400, res.text
    assert res.json()["error_code"] == "UNSUBSCRIBE_LINK_INVALID"


def test_el_contexto_del_lote_no_tiene_bajas_por_defecto() -> None:
    """Revision de fix/legal-datos (2026-09-25): con ``bajas`` vacio por
    defecto, un llamador nuevo que se olvidara de cargarlas le mandaria el
    mail promocional a quien se dio de baja. Es obligatorio."""
    from modules.payments.jobs import _ContextoDelLote

    with pytest.raises(TypeError):
        _ContextoDelLote(admins={}, tiendas={}, turnos={})  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_la_baja_por_post_tiene_la_misma_semantica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de fix/legal-datos (2026-09-25): los escaneres de correo
    abren los links GET del mail. La pagina de confirmacion del front hace
    ``POST /public/unsubscribe`` con ``{token}``; el GET sigue por ahora."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _token, _pid, turno = await _turno(client, test_session, "baja-post")
    tienda, cliente = turno.store_id, str(turno.client_id)
    link = make_unsubscribe_token(tienda, cliente)

    primera = await client.post("/public/unsubscribe", json={"token": link})
    segunda = await client.post("/public/unsubscribe", json={"token": link})
    mala = await client.post("/public/unsubscribe", json={"token": link[:-3] + "xyz"})
    rara = await client.post("/public/unsubscribe", json={"token": "a.b.1.é"})
    vacia = await client.post("/public/unsubscribe", json={"token": ""})

    assert primera.status_code == 200, primera.text
    assert primera.json() == segunda.json() == {"status": "unsubscribed"}
    for res in (mala, rara):
        assert res.status_code == 400, res.text
        assert res.json()["error_code"] == "UNSUBSCRIBE_LINK_INVALID"
    assert vacia.status_code == 422, vacia.text
    [baja] = await _bajas(test_session)
    assert baja.client_id == cliente and baja.store_id == tienda
