"""Rafaga: el cliente reprograma un turno con la sena por WhatsApp pendiente.

Re-revision de la PR #108 (W3, CLAUDE.md §4). Reprogramar desde "Mis turnos"
una sena por WhatsApp la muda al turno nuevo (``carry_manual_deposit``): vence
el cobro del original y crea uno ``manual`` ``pending`` para el nuevo, en la
misma transaccion que cancela el original. Lo que SQLite no prueba es la
carrera con una sesion por request. Los caminos lockean el TURNO primero
(``_lock_client_appointment``, ``lock_appointment_status``) y despues el
cobro (regla 7), asi que se serializan sobre la fila del turno original.

Lo que se fija:

- N reprogramaciones del mismo turno al mismo horario nuevo: 1 x 200 y
  N-1 x 409 (el original ya no esta activo), cero 5xx, UN solo cobro vivo;
- una reprogramacion contra la confirmacion manual del personal: gane quien
  gane, nunca dos cobros vivos y nunca un ``pending_payment`` sin cobro vivo.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

# Por debajo del rate limit de escritura publica por turno y telefono, como
# la rafaga de cancelaciones del portal (``test_pg_cancelar_con_cobro_vivo``).
RAFAGA = 6
TELEFONO = "+5491155550888"


def _mp_prohibido(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    llamadas: list[str] = []

    async def prohibido(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append(path)
        raise AssertionError(f"una sena por WhatsApp no llama a MP: {path}")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", prohibido)
    return llamadas


async def _sena_por_whatsapp_verificada(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> tuple[str, str, str, datetime]:
    """(tienda, token del admin, turno, dia): turno con la sena del 30 % por
    WhatsApp pendiente y el telefono del cliente verificado por OTP."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    canal = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"whatsapp_number": "11 5555 0303"},
    )
    assert canal.status_code == 200, canal.text
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente WhatsApp",
            "client_email": f"cliente-{slug}@example.com",
            "client_phone": TELEFONO,
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": f"{slug}-alta-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["deposit_channel"] == "whatsapp", reserva.text
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text
    return store, token, str(reserva.json()["public_id"]), dia


def _reprogramar(client: AsyncClient, turno: str, inicio: datetime, clave: str) -> Any:
    return client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": inicio.isoformat(),
            "idempotency_key": clave,
        },
    )


async def _cobros_de_la_tienda(
    owner_engine: AsyncEngine, store_public_id: str
) -> list[tuple[str, str, str | None, str | None]]:
    """(turno, estado del turno, estado del cobro, proveedor) de la tienda."""
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "select a.id, a.status, p.status, p.provider "
                    "from appointments a join stores s on s.id = a.store_id "
                    "left join payments p on p.appointment_id = a.id "
                    "where s.public_id = :store"
                ),
                {"store": store_public_id},
            )
        ).all()
    return [(str(f[0]), str(f[1]), f[2], f[3]) for f in filas]


def _assert_consistente(filas: list[tuple[str, str, str | None, str | None]]) -> None:
    vivos = [f for f in filas if f[2] in ("pending", "rejected")]
    assert len(vivos) <= 1, filas
    for turno, estado, cobro, proveedor in filas:
        if estado == "pending_payment":
            # Un turno esperando la sena tiene su cobro vivo, y es manual.
            assert (cobro, proveedor) == ("pending", "manual"), filas
        if cobro in ("pending", "rejected"):
            assert estado == "pending_payment", filas


@pytest.mark.asyncio
async def test_rafaga_de_reprogramaciones_de_una_sena_por_whatsapp(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _token, turno, dia = await _sena_por_whatsapp_verificada(
        client, app_sessions, monkeypatch, "pg-wa-reprograma-rafaga"
    )
    llamadas = _mp_prohibido(monkeypatch)
    nuevo = dia.replace(hour=15, minute=0, second=0, microsecond=0)

    respuestas: list[Response] = await asyncio.gather(
        *(
            _reprogramar(client, turno, nuevo, f"pg-wa-reprograma-{i:06d}")
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), [r.text[:200] for r in respuestas]
    assert codigos.count(200) == 1, codigos
    assert set(codigos) == {200, 409}, codigos
    filas = await _cobros_de_la_tienda(owner_engine, store)
    _assert_consistente(filas)
    # El original cancelado con su cobro vencido y UN turno nuevo esperando
    # la sena con su cobro manual vivo.
    assert sorted((f[1], f[2]) for f in filas) == [
        ("cancelled", "expired"),
        ("pending_payment", "pending"),
    ], filas
    assert llamadas == []


@pytest.mark.asyncio
async def test_reprogramar_contra_la_confirmacion_manual_no_deja_cobros_raros(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, token, turno, dia = await _sena_por_whatsapp_verificada(
        client, app_sessions, monkeypatch, "pg-wa-reprograma-vs-confirma"
    )
    llamadas = _mp_prohibido(monkeypatch)
    nuevo = dia.replace(hour=15, minute=0, second=0, microsecond=0)

    reprogramacion, confirmacion = await asyncio.gather(
        _reprogramar(client, turno, nuevo, "pg-wa-reprograma-vs-000001"),
        client.post(
            f"/payments/{turno}/manual-confirm",
            headers=auth_headers(token),
            json={"notes": "transferencia por WhatsApp"},
        ),
    )

    assert reprogramacion.status_code < 500, reprogramacion.text
    assert confirmacion.status_code < 500, confirmacion.text
    filas = await _cobros_de_la_tienda(owner_engine, store)
    _assert_consistente(filas)
    if reprogramacion.status_code == 200:
        # Gano la reprogramacion: el original ya estaba soltado al confirmar.
        assert confirmacion.status_code == 409, confirmacion.text
        assert confirmacion.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"
        assert sorted((f[1], f[2]) for f in filas) == [
            ("cancelled", "expired"),
            ("pending_payment", "pending"),
        ], filas
    else:
        # Gano la confirmacion: un turno pagado no lo mueve el cliente.
        assert confirmacion.status_code == 200, confirmacion.text
        assert reprogramacion.status_code == 409, reprogramacion.text
        assert (
            reprogramacion.json()["error_code"] == "PAID_APPOINTMENT_RESCHEDULE_DENIED"
        )
        assert [(f[1], f[2]) for f in filas] == [("confirmed", "manual_confirmed")]
    assert llamadas == []
