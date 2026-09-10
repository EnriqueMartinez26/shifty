"""Bloqueos de agenda sobre turnos ya tomados (Fase 1, 2026-09-10).

Antes el bloqueo se creaba sin mirar los turnos reservados: quedaban activos
adentro (huerfanos), con recordatorio y todo. Ahora hay preview, el alta
exige confirmar la cancelacion en bloque (solo administradores), los turnos
que no se pueden cancelar solos (esperando pago, con sena acreditada) se
listan para decision humana, y el cliente recibe un mail por el outbox.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointment_blocks.service import expand_ranges
from modules.appointments.model import Appointment
from modules.audit.model import AuditLog
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


def test_expand_ranges_semanal_respeta_tope_y_hasta() -> None:
    inicio = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    fin = inicio + timedelta(hours=2)
    rangos = expand_ranges(inicio, fin, "weekly", inicio + timedelta(days=15), 10)
    assert [r[0].date().isoformat() for r in rangos] == [
        "2026-09-14",
        "2026-09-21",
        "2026-09-28",
    ]
    assert expand_ranges(inicio, fin, "none", None, 5) == [(inicio, fin)]
    assert len(expand_ranges(inicio, fin, "daily", None, 4)) == 4


async def _tienda_con_turnos(
    client: AsyncClient, slug: str, *, cantidad: int = 2
) -> tuple[str, str, str, str, list[str], datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    turnos: list[str] = []
    for i in range(cantidad):
        res = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": (base + timedelta(hours=i)).isoformat(),
                "client_name": f"Cliente {i}",
                "client_email": f"cliente{i}-{slug}@example.com",
                "client_phone": f"+54911555{i:05d}",
                "idempotency_key": f"bloqueo-{slug}-{i:03d}",
            },
        )
        assert res.status_code == 201, res.text
        turnos.append(str(res.json()["public_id"]))
    return store, token, service, staff, turnos, base


@pytest.mark.asyncio
async def test_preview_lista_los_turnos_que_caen_en_el_bloqueo(
    client: AsyncClient,
) -> None:
    _, token, _, staff, turnos, base = await _tienda_con_turnos(client, "prev")
    res = await client.post(
        "/appointment-blocks/preview",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=1, minutes=30)).isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["ranges"] == 1
    assert {a["public_id"] for a in cuerpo["affected"]} == set(turnos)
    primero = cuerpo["affected"][0]
    assert primero["cancellable"] is True and primero["blocker"] is None
    assert primero["client_phone"], "el admin ve el telefono para avisar por wa.me"


@pytest.mark.asyncio
async def test_sin_confirmar_el_alta_responde_409_y_no_deja_huerfanos(
    client: AsyncClient,
) -> None:
    _, token, _, staff, turnos, base = await _tienda_con_turnos(client, "sin409")
    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=3)).isoformat(),
            "reason": "Vacaciones",
        },
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "BLOCK_HAS_APPOINTMENTS"
    assert res.json()["detail"]["affected"] == len(turnos)
    bloqueos = await client.get("/appointment-blocks/", headers=auth_headers(token))
    assert bloqueos.json() == []


@pytest.mark.asyncio
async def test_confirmar_cancela_en_bloque_audita_y_avisa_por_mail(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    enviados: list[tuple[str, str, str]] = []

    async def buzon(to: str, subject: str, body: str) -> bool:
        enviados.append((to, subject, body))
        return True

    monkeypatch.setattr(tasks, "_send_email", buzon)
    _, token, _, staff, turnos, base = await _tienda_con_turnos(client, "cancela")

    res = await client.post(
        "/appointment-blocks/batch",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=3)).isoformat(),
            "reason": "Vacaciones",
            "recurrence": "weekly",
            "recurrence_until": (base + timedelta(days=8)).isoformat(),
            "cancel_affected": True,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["created"] == 2  # esta semana y la que viene

    estados = (
        (
            await test_session.execute(
                select(Appointment.status).where(Appointment.id.in_(turnos))
            )
        )
        .scalars()
        .all()
    )
    assert set(estados) == {"cancelled"}

    auditados = (
        (
            await test_session.execute(
                select(AuditLog).where(
                    AuditLog.resource_type == "Appointment",
                    AuditLog.resource_id.in_(turnos),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(auditados) == len(turnos)
    assert all((a.payload_after or {}).get("reason") == "blocked" for a in auditados)

    pendientes = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == "appointment.cancelled_by_block"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(pendientes) == len(turnos)

    resultado = await process_outbox_batch(test_session)
    assert resultado["processed"] >= len(turnos)
    # El buzon tambien recibe "reserva registrada" y los avisos al dueno.
    cancelaciones = [e for e in enviados if e[1].startswith("Turno cancelado")]
    assert len(cancelaciones) == len(turnos)
    assert {e[0] for e in cancelaciones} == {
        "cliente0-cancela@example.com",
        "cliente1-cancela@example.com",
    }
    assert "Vacaciones" in cancelaciones[0][2]


@pytest.mark.asyncio
async def test_un_turno_esperando_pago_no_se_cancela_solo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token, _, staff, turnos, base = await _tienda_con_turnos(
        client, "pend", cantidad=1
    )
    # Simula que ese turno esta esperando la sena en Mercado Pago.
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == turnos[0])
        )
    ).scalar_one()
    turno.apply_status_transition("pending_payment")
    await test_session.commit()

    preview = await client.post(
        "/appointment-blocks/preview",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=2)).isoformat(),
        },
    )
    afectado = preview.json()["affected"][0]
    assert afectado["cancellable"] is False and afectado["blocker"] == "pending_payment"

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=2)).isoformat(),
            "cancel_affected": True,
        },
    )
    assert res.status_code == 201, res.text
    await test_session.refresh(turno)
    assert turno.status == "pending_payment", "requiere liberar a mano, no cancelar"


@pytest.mark.asyncio
async def test_el_personal_no_puede_cancelar_en_bloque(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token, _, staff, _, base = await _tienda_con_turnos(
        client, "staffno", cantidad=1
    )
    # Crea un usuario con rol personal y entra con el.
    alta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": "recep-staffno@example.com",
            "password": "Password123!",
            "first_name": "Rece",
            "last_name": "Pcion",
            "role": "staff",
        },
    )
    assert alta.status_code == 201, alta.text
    login = await client.post(
        "/auth/login",
        json={"email": "recep-staffno@example.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    token_staff = str(login.json()["access_token"])

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token_staff),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=2)).isoformat(),
            "cancel_affected": True,
        },
    )
    assert res.status_code == 403, res.text
