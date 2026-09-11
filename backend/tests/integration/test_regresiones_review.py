"""Regresiones del review de las Fases 2-5 (2026-09-11).

Cada test reproduce un defecto encontrado al revisar el rango 7ed6f17..eceafd8.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.model import Payment
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_lista_de_espera import _alta, _reservar, _tienda
from tests.integration.test_mails_al_cliente import Buzon


async def _mp_fake(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "pref-regresion",
        "init_point": "https://www.mercadopago.com/checkout/v1/redirect?pref=x",
    }


@pytest.mark.asyncio
async def test_el_link_del_panel_no_pisa_la_sena_calculada_por_la_regla(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El cobro nacia con la sena de la regla y generar el link desde el panel
    lo re-tarifaba a la sena base: la tienda cobraba la mitad, el snapshot
    quedaba mintiendo y el webhook rechazaba el importe para siempre."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", _mp_fake)
    store, token = await register_and_login(
        client, slug="link-panel", email="link-panel@example.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert gateway.status_code == 200, gateway.text
    reglas = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"deposit_far_notice_days": 7, "deposit_far_notice_extra_percent": 20},
    )
    assert reglas.status_code == 200, reglas.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, service, email="pro-link@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=10)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente",
            "client_phone": "+5491155550777",
            "payment_method": "auto",
            "idempotency_key": "link-panel-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    # base 30% + 20 por antelacion = 50% de 10000
    assert reserva.json()["payment_amount"] == 5000.0
    pid = reserva.json()["public_id"]

    link = await client.post(
        f"/payments/preferences/{pid}", headers=auth_headers(token)
    )
    assert link.status_code == 200, link.text

    test_session.expire_all()
    pago = (
        await test_session.execute(select(Payment).where(Payment.appointment_id == pid))
    ).scalar_one()
    assert str(pago.amount) == "5000.00", "el panel re-tarifo a la sena base"
    assert pago.deposit_rule is not None
    assert pago.deposit_rule["amount"] == "5000.00"


@pytest.mark.asyncio
async def test_borrar_un_bloqueo_no_ofrece_por_mail_un_horario_fuera_de_grilla(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El rango de un bloqueo (12:30 a 14:00) no cae en la grilla que ve el
    cliente: se le avisa al duenio, pero no se manda un mail a un horario que
    no existe."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "bloqueo-grilla")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text

    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": (slot - timedelta(minutes=30)).isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
            "reason": "Vacaciones",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    borrar = await client.delete(
        f"/appointment-blocks/{bloqueo.json()['public_id']}",
        headers=auth_headers(token),
    )
    assert borrar.status_code == 204, borrar.text

    from modules.payments.jobs import process_outbox_batch

    await process_outbox_batch(test_session)

    entrada = (await test_session.execute(select(WaitlistEntry))).scalar_one()
    assert entrada.status == "waiting"
    assert not any(a.startswith("Se libero un turno") for _t, a, _c in buzon.enviados)


@pytest.mark.asyncio
async def test_reprogramar_desde_el_panel_le_avisa_al_cliente(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La fila nueva nace despues de starts_at-24h, asi que ya no le toca el
    recordatorio de 24 horas: sin este mail el cliente no se enteraba."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "reprogramado")
    pid = await _reservar(client, store, service, staff, slot, "reprogramado-000001")

    mover = await client.patch(
        f"/appointments/{pid}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": (slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "reprogramado-mover-0001",
        },
    )
    assert mover.status_code == 200, mover.text

    aviso = next(e for e in buzon.enviados if e[1].startswith("Te movimos el turno"))
    assert aviso[0] == "titular@example.com"
    assert "movio tu turno" in aviso[2]


@pytest.mark.asyncio
async def test_el_texto_libre_de_la_lista_de_espera_rechaza_caracteres_de_control(
    client: AsyncClient,
) -> None:
    store, _token, service, _staff, slot = await _tienda(client, "espera-control")

    res = await client.post(
        "/public/waitlist",
        json=_alta(store, service, slot, client_name="Lucia‮evil"),
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_reprogramar_conserva_el_contacto_del_cliente_no_el_del_admin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El turno nuevo copiaba el nombre, mail y telefono de QUIEN reprograma:
    la confirmacion, el recordatorio y el boton de WhatsApp apuntaban a la
    propia tienda en vez de al cliente."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "contacto-reprog")
    pid = await _reservar(client, store, service, staff, slot, "contacto-reprog-01")

    mover = await client.patch(
        f"/appointments/{pid}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": (slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "contacto-reprog-mover01",
        },
    )
    assert mover.status_code == 200, mover.text

    agenda = await client.get(
        "/appointments/search", headers=auth_headers(token), params={"page_size": 50}
    )
    assert agenda.status_code == 200, agenda.text
    nuevo = next(
        r
        for r in agenda.json()["results"]
        if r["public_id"] == mover.json()["public_id"]
    )
    assert nuevo["client_name"] == "Titular"
    assert nuevo["client_phone"] == "5491155550200"
