"""Derechos del titular: la tienda exporta y anonimiza a un cliente (PV-05, L3-06).

2026-09-25. No habia forma de ejercer acceso ni supresion: la unica "baja"
era desactivar y los datos quedaban para siempre. Ahora, solo el admin de la
tienda:

- ``GET /users/{client_id}/export``: datos del cliente y sus turnos, cobros,
  movimientos de fiado y lista de espera de ESTA tienda, en JSON;
- ``POST /users/{client_id}/anonymize``: reemplaza nombre, telefono, email,
  respuestas de la reserva y notas por valores neutros; conserva importes,
  fechas y estados para la contabilidad; deja al cliente inactivo. 409 si
  tiene un cobro vivo o un turno activo a futuro.

Solo cuentas con rol cliente de la tienda del admin (personal, admins u otra
tienda: 404 neutro). Cada pedido deja una entrada de auditoria sin datos
personales.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment
from modules.audit.model import AuditLog
from modules.ledger.model import CustomerLedger
from modules.payments.model import Payment
from modules.users.model import User
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_fiado_del_profesional import _login, _usuario
from tests.integration.test_lista_de_espera import _tienda
from tests.integration.test_mails_al_cliente import Buzon

NOMBRE = "Rosa Titular"
TELEFONO = "+5491170090001"
# El email del cliente es unico en toda la plataforma (hasta PV-01): uno por caso.
EMAIL = "rosa.titular@example.com"
NOTA = "Prefiere los martes, alergica al latex"
RESPUESTA = "Control por migrana"


class _Caso:
    email = ""
    store = ""
    token = ""
    turno = ""
    cliente = ""


async def _caso(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> _Caso:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    c = _Caso()
    c.email = EMAIL.replace("titular", slug)
    c.store, c.token, service, staff, slot = await _tienda(client, slug)
    ajustes = await client.patch(
        "/stores/me",
        headers=auth_headers(c.token),
        json={
            "custom_client_fields": [
                {
                    "key": "motivo",
                    "label": "Motivo",
                    "type": "text",
                    "required": False,
                    "options": [],
                }
            ]
        },
    )
    assert ajustes.status_code == 200, ajustes.text
    fiado = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(c.token), json={"ledger": True}
    )
    assert fiado.status_code == 200, fiado.text
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": c.store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": NOMBRE,
            "client_phone": TELEFONO,
            "client_email": c.email,
            "notes": NOTA,
            "custom_fields": {"motivo": RESPUESTA},
            "accepts_terms": True,
            "idempotency_key": f"titular-{slug}-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    c.turno = str(reserva.json()["public_id"])
    turno = (
        await test_session.execute(select(Appointment).where(Appointment.id == c.turno))
    ).scalar_one()
    assert turno.client_id is not None
    c.cliente = turno.client_id
    carga = await client.post(
        f"/ledger/customers/{c.cliente}/movements",
        headers=auth_headers(c.token),
        json={"movement_type": "charge", "amount": "1500.00", "notes": NOTA},
    )
    assert carga.status_code == 200, carga.text
    return c


async def _cancelar(client: AsyncClient, c: _Caso) -> None:
    res = await client.patch(
        f"/appointments/{c.turno}/cancel",
        headers=auth_headers(c.token),
        json={"reason": "pedido del cliente"},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_el_admin_exporta_los_datos_del_cliente_de_su_tienda(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await _caso(client, test_session, monkeypatch, "titular-exporta")

    res = await client.get(f"/users/{c.cliente}/export", headers=auth_headers(c.token))

    assert res.status_code == 200, res.text
    datos = res.json()
    assert datos["client"]["public_id"] == c.cliente
    assert datos["client"]["email"] == c.email
    assert datos["client"]["phone"] == TELEFONO.lstrip("+")
    assert NOMBRE in datos["client"]["full_name"]
    [turno] = datos["appointments"]
    assert turno["public_id"] == c.turno
    assert turno["notes"] == NOTA
    assert turno["intake_answers"] == {"motivo": RESPUESTA}
    assert turno["terms_accepted_at"] is not None
    [movimiento] = datos["ledger"]
    assert Decimal(movimiento["amount"]) == Decimal("1500.00")
    assert movimiento["notes"] == NOTA
    assert datos["payments"] == [] and datos["waitlist"] == []
    assert "exported_at" in datos

    auditoria = (
        (
            await test_session.execute(
                select(AuditLog).where(AuditLog.resource_id == c.cliente)
            )
        )
        .scalars()
        .all()
    )
    assert [a.action for a in auditoria] == ["export"]
    _sin_datos_personales(auditoria, c.email)


def _sin_datos_personales(filas: Sequence[AuditLog], email: str) -> None:
    for fila in filas:
        texto = json.dumps([fila.payload_before, fila.payload_after, fila.context])
        for dato in (NOMBRE, "Rosa", email, TELEFONO.lstrip("+"), NOTA, RESPUESTA):
            assert dato not in texto, texto


@pytest.mark.asyncio
async def test_con_un_turno_activo_a_futuro_no_se_anonimiza(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await _caso(client, test_session, monkeypatch, "titular-activo")

    res = await client.post(
        f"/users/{c.cliente}/anonymize", headers=auth_headers(c.token)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "CLIENT_HAS_ACTIVE_APPOINTMENTS"
    test_session.expire_all()
    cliente = await test_session.get(User, c.cliente)
    assert cliente is not None and cliente.email == c.email


@pytest.mark.asyncio
async def test_con_un_cobro_vivo_no_se_anonimiza(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await _caso(client, test_session, monkeypatch, "titular-cobro")
    await _cancelar(client, c)
    turno = await test_session.get(Appointment, c.turno)
    assert turno is not None
    test_session.add(
        Payment(
            store_id=turno.store_id,
            appointment_id=turno.id,
            amount=Decimal("500.00"),
            status="pending",
        )
    )
    await test_session.commit()

    res = await client.post(
        f"/users/{c.cliente}/anonymize", headers=auth_headers(c.token)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "CLIENT_HAS_LIVE_CHARGE"


@pytest.mark.asyncio
async def test_anonimizar_borra_los_datos_y_conserva_importes_fechas_y_estados(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = await _caso(client, test_session, monkeypatch, "titular-anonimiza")
    await _cancelar(client, c)
    antes = await test_session.get(Appointment, c.turno)
    assert antes is not None
    inicio, precio = antes.starts_at, antes.price_amount
    test_session.add(
        WaitlistEntry(
            store_id=antes.store_id,
            client_id=c.cliente,
            client_name=NOMBRE,
            client_phone=TELEFONO.lstrip("+"),
            client_email=c.email,
            service_id=antes.service_id,
            window_starts_at=inicio,
            window_ends_at=inicio + timedelta(hours=2),
            notes=NOTA,
        )
    )
    await test_session.commit()

    res = await client.post(
        f"/users/{c.cliente}/anonymize", headers=auth_headers(c.token)
    )

    assert res.status_code == 200, res.text
    assert res.json() == {"status": "anonymized"}
    test_session.expire_all()
    cliente = await test_session.get(User, c.cliente)
    assert cliente is not None
    assert cliente.is_active is False
    assert cliente.phone is None
    assert cliente.email.endswith(".noreply") and "rosa" not in cliente.email
    assert not tasks.is_deliverable_email(cliente.email)
    turno = await test_session.get(Appointment, c.turno)
    assert turno is not None
    assert turno.client_email is None and turno.client_phone is None
    assert turno.notes is None and turno.notes_staff is None
    assert turno.intake_answers == {}
    assert NOMBRE not in turno.client_name
    assert turno.status == "cancelled"
    assert turno.starts_at == inicio and turno.price_amount == precio
    movimiento = (
        await test_session.execute(
            select(CustomerLedger).where(CustomerLedger.client_id == c.cliente)
        )
    ).scalar_one()
    assert movimiento.notes is None and movimiento.amount == Decimal("1500.00")
    espera = (
        await test_session.execute(
            select(WaitlistEntry).where(WaitlistEntry.client_id == c.cliente)
        )
    ).scalar_one()
    assert espera.client_email is None and espera.notes is None
    assert NOMBRE not in espera.client_name and "7009" not in espera.client_phone
    assert espera.status == "cancelled"

    exportado = await client.get(
        f"/users/{c.cliente}/export", headers=auth_headers(c.token)
    )
    assert exportado.status_code == 200, exportado.text
    texto = exportado.text
    for dato in (NOMBRE, c.email, TELEFONO.lstrip("+"), NOTA, RESPUESTA):
        assert dato not in texto
    auditoria = (
        (
            await test_session.execute(
                select(AuditLog).where(AuditLog.resource_id == c.cliente)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(a.action for a in auditoria) == ["anonymize", "export"]
    _sin_datos_personales(auditoria, c.email)


@pytest.mark.asyncio
async def test_otra_tienda_y_cuentas_del_personal_son_404_y_el_profesional_403(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await _caso(client, test_session, monkeypatch, "titular-a")
    b = await _caso(client, test_session, monkeypatch, "titular-b")
    await _cancelar(client, b)
    pro = await _usuario(
        client,
        a.token,
        email="panel-titular-a@example.com",
        rol="staff",
        nombre="Pro",
        apellido="Fesional",
    )
    profesional = await _login(client, "panel-titular-a@example.com")

    for ruta, verbo in (("export", "GET"), ("anonymize", "POST")):
        ajeno = await client.request(
            verbo, f"/users/{b.cliente}/{ruta}", headers=auth_headers(a.token)
        )
        personal = await client.request(
            verbo, f"/users/{pro}/{ruta}", headers=auth_headers(a.token)
        )
        sin_permiso = await client.request(
            verbo, f"/users/{a.cliente}/{ruta}", headers=profesional
        )
        for res in (ajeno, personal):
            assert res.status_code == 404, res.text
            assert NOMBRE not in res.text and b.email not in res.text
        assert sin_permiso.status_code == 403, sin_permiso.text

    test_session.expire_all()
    cliente_b = await test_session.get(User, b.cliente)
    assert cliente_b is not None
    assert cliente_b.email == b.email and cliente_b.is_active is True
