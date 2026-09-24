"""El lote del outbox resuelve admins y tiendas con una consulta, no por mensaje.

F1-23 (plan de rendimiento, R3-07, 2026-09-24; regla 12): por cada mensaje
que genera un aviso al dueno, ``_store_owner_mails`` consultaba los admins de
SU tienda, y por cada "sena acreditada" ``_client_confirmation_mail`` leia la
``Store`` del turno. Con el lote de 25 (100 por el endpoint del panel) eran
hasta un SELECT de ``users`` y uno de ``stores`` por mensaje dentro de la
transaccion que sostiene el ``FOR UPDATE SKIP LOCKED``.

Ahora se resuelven antes del ``for`` con un ``in_()`` sobre las tiendas del
lote, y cada consulta conserva el filtro por ``store_id`` (CLAUDE.md §2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

TIENDAS = 3


async def _turno_confirmado(client: AsyncClient, token: str, slug: str) -> str:
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return str(reserva.json()["public_id"])


@pytest.mark.asyncio
async def test_el_lote_resuelve_admins_y_tiendas_con_una_consulta_cada_uno(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    tiendas: list[str] = []
    for i in range(TIENDAS):
        slug = f"outbox-n1-{i}"
        _public, token = await register_and_login(
            client, slug=slug, email=f"{slug}@test.com"
        )
        turno_publico = await _turno_confirmado(client, token, slug)
        turno = (
            await test_session.execute(
                select(Appointment).where(Appointment.id == turno_publico)
            )
        ).scalar_one()
        if turno.status != AppointmentStatus.CONFIRMED.value:
            turno.apply_status_transition(AppointmentStatus.CONFIRMED)
        # El turno del panel no trae email del cliente: se fija para que la
        # confirmacion de la sena tenga a quien ir.
        turno.client_email = f"cliente-{slug}@t.com"
        tiendas.append(turno.store_id)
        for evento in (
            NotificationType.PAYMENT_APPROVED.value,
            NotificationType.SUBSCRIPTION_EXPIRING.value,
        ):
            test_session.add(
                OutboxMessage(
                    store_id=turno.store_id,
                    event_type=evento,
                    payload={"appointment_id": turno.id, "days_left": 3},
                )
            )
    await test_session.commit()
    # Nada en el mapa de identidad: la tienda la tiene que leer el lote.
    test_session.expunge_all()
    # Solo cuentan los mails del lote, no los del alta del turno.
    buzon.enviados.clear()

    lecturas: dict[str, list[str]] = {"users": [], "stores": []}

    def contar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        for tabla, vistas in lecturas.items():
            if f"FROM {tabla}" in statement:
                vistas.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", contar)
    try:
        resultado = await process_outbox_batch(test_session)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", contar)

    assert resultado["processed"] == TIENDAS * 2, resultado
    assert len(lecturas["users"]) == 1, lecturas["users"]
    assert len(lecturas["stores"]) == 1, lecturas["stores"]
    # Tenancy: las dos consultas siguen acotadas a las tiendas del lote.
    assert "users.store_id IN" in lecturas["users"][0]
    assert "stores.id IN" in lecturas["stores"][0]
    # Y el resultado es el mismo: un aviso por mensaje a SU admin, mas la
    # confirmacion al cliente de cada sena acreditada.
    destinatarios = sorted(to for to, _asunto, _cuerpo in buzon.enviados)
    esperados = sorted(
        [f"outbox-n1-{i}@test.com" for i in range(TIENDAS)] * 2
        + [f"cliente-outbox-n1-{i}@t.com" for i in range(TIENDAS)]
    )
    assert destinatarios == esperados
    assert len(set(tiendas)) == TIENDAS
    assert await test_session.get(Store, tiendas[0]) is not None
