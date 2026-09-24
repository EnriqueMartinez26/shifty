"""Caracterizacion del alta, la reprogramacion y la liberacion del panel (B1-12).

Audit B1-12 (2026-09-19), regla 29 de CLAUDE.md: ``AppointmentService.book``
(129 lineas), ``reschedule`` (158) y ``release_pending`` (90). Antes de
partirlas estos tests fijan el camino completo tal como es HOY: cuerpos,
filas, auditoria, eventos del outbox, invalidaciones del cache, mails y el
orden commit -> cache -> mail. Pasan sobre la base y siguen pasando despues
del refactor sin cambiar una asercion.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment
from modules.audit.model import AuditLog
from modules.payments.model import Payment
from tests.integration.test_caracterizacion_alta_publica import (
    _contar,
    _espiar_orden,
    _eventos,
    _redis,
    _Tienda,
    _tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon


def _espiar_orden_con_commit_plano(
    session: AsyncSession, redis: Any, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """``_espiar_orden`` mas el commit PLANO de ``AsyncSession``.

    Desde F1-05 (2026-09-24) el service commitea con ``AsyncSession.commit``
    antes del mail, para no mandarlo con una transaccion abierta: ese commit
    no pasa por el metodo de la instancia que espia ``_espiar_orden``.
    """
    orden = _espiar_orden(session, redis, monkeypatch)
    commit_plano = AsyncSession.commit

    async def commit(self: AsyncSession) -> None:
        orden.append("commit")
        await commit_plano(self)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    return orden


def _buzon_en_orden(orden: list[str] | None, monkeypatch: pytest.MonkeyPatch) -> Buzon:
    buzon = Buzon()

    async def enviar(to: str, subject: str, body: str, smtp: Any = None) -> bool:
        if orden is not None:
            orden.append("mail")
        return await buzon(to, subject, body)

    monkeypatch.setattr(tasks, "_send_email", enviar)
    return buzon


async def _auditoria(session: AsyncSession) -> list[tuple[str, str, Any]]:
    session.expire_all()
    filas = await session.execute(select(AuditLog).order_by(AuditLog.id.asc()))
    return [(a.action, a.resource_type, a.payload_after) for a in filas.scalars()]


async def _alta_panel(
    client: AsyncClient, t: _Tienda, inicio: datetime, clave: str
) -> Any:
    return await client.post(
        "/appointments/",
        headers=auth_headers(t.token),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": inicio.isoformat(),
            "notes": "Del panel",
            "idempotency_key": clave,
        },
    )


async def _turno(session: AsyncSession, turno_id: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == turno_id))
    ).scalar_one()


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alta_del_panel_cuerpo_filas_auditoria_y_orden(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "carac-panel-alta")
    auditoria_antes = len(await _auditoria(test_session))
    orden = _espiar_orden_con_commit_plano(test_session, await _redis(), monkeypatch)
    buzon = _buzon_en_orden(orden, monkeypatch)

    res = await _alta_panel(client, t, t.slot, "carac-panel-alta-0001")

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert {k: v for k, v in cuerpo.items() if k not in {"public_id"}} | {
        "starts_at": None,
        "ends_at": None,
    } == {
        "service_id": t.service,
        "staff_id": t.staff,
        "starts_at": None,
        "ends_at": None,
        "status": "pending",
        "notes": "Del panel",
        "notes_staff": None,
        "intake_answers": {},
        "cancelled_at": None,
        "completed_at": None,
    }
    assert ensure_utc_aware(datetime.fromisoformat(cuerpo["starts_at"])) == t.slot
    # Commit -> invalidacion -> mail de confirmacion al actor. Hasta F1-05
    # (2026-09-24) el mail iba antes de la invalidacion: con un SMTP lento el
    # horario tomado seguia libre en la disponibilidad publica.
    assert orden == ["commit", "cache", "mail"], orden
    assert [m[0] for m in buzon.enviados] == ["carac-panel-alta@example.com"]
    fila = await _turno(test_session, cuerpo["public_id"])
    assert (fila.price_amount, fila.client_email, fila.idempotency_key) == (
        Decimal("10000.00"),
        "carac-panel-alta@example.com",
        "carac-panel-alta-0001",
    )
    assert (fila.client_name, fila.expires_at) == ("Admin Demo", None)
    nuevas = (await _auditoria(test_session))[auditoria_antes:]
    assert [(a[0], a[1]) for a in nuevas] == [("create", "Appointment")]
    # Hoy el alta audita "status": None (el default del modelo recien se
    # aplica en el flush). Se fija tal cual: B1-12 no cambia comportamiento.
    assert nuevas[0][2]["status"] is None
    assert await _eventos(test_session) == []


@pytest.mark.asyncio
async def test_alta_del_panel_choque_y_bloqueo_con_sugerencia(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "carac-panel-choque")
    _buzon_en_orden(None, monkeypatch)
    assert (await _alta_panel(client, t, t.slot, "carac-pc-0001")).status_code == 201
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(t.token),
        json={
            "staff_id": t.staff,
            "starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "ends_at": (t.slot + timedelta(hours=3)).isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text

    choque = await _alta_panel(client, t, t.slot, "carac-pc-0002")
    bloqueado = await _alta_panel(
        client, t, t.slot + timedelta(hours=2), "carac-pc-0003"
    )

    assert choque.status_code == 409, choque.text
    assert choque.json()["error_code"] == "APPOINTMENT_CONFLICT"
    sugerencia = choque.json()["detail"]["suggestion"]
    assert ensure_utc_aware(datetime.fromisoformat(sugerencia)) == (
        t.slot + timedelta(minutes=30)
    )
    assert bloqueado.status_code == 409, bloqueado.text
    assert bloqueado.json()["error_code"] == "SCHEDULE_BLOCKED"
    assert ensure_utc_aware(
        datetime.fromisoformat(bloqueado.json()["detail"]["suggestion"])
    ) == t.slot + timedelta(hours=3)
    assert await _contar(test_session, Appointment) == 1


# ---------------------------------------------------------------------------
# Reprogramacion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprogramar_del_panel_cuerpo_filas_auditoria_outbox_y_orden(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "carac-panel-repro")
    _buzon_en_orden(None, monkeypatch)
    alta = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.slot.isoformat(),
            "client_name": "Cliente Panel",
            "client_phone": "+5491155559001",
            "accepts_terms": True,
            "client_email": "cliente-panel@example.com",
            "notes": "Traer estudios",
            "idempotency_key": "carac-panel-repro-alta",
        },
    )
    assert alta.status_code == 201, alta.text
    turno = alta.json()["public_id"]
    eventos_antes = len(await _eventos(test_session))
    auditoria_antes = len(await _auditoria(test_session))
    orden = _espiar_orden_con_commit_plano(test_session, await _redis(), monkeypatch)
    buzon = _buzon_en_orden(orden, monkeypatch)
    nuevo_inicio = t.slot + timedelta(hours=2)

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": nuevo_inicio.isoformat(),
            "idempotency_key": "carac-panel-repro-0001",
        },
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["public_id"] != turno
    assert (cuerpo["status"], cuerpo["notes"], cuerpo["staff_id"]) == (
        "pending",
        "Traer estudios",
        t.staff,
    )
    # Commit -> invalidacion -> mail de reprogramacion al CLIENTE.
    assert orden == ["commit", "cache", "mail"], orden
    assert [m[0] for m in buzon.enviados] == ["cliente-panel@example.com"]
    assert (await _turno(test_session, turno)).status == "cancelled"
    nuevo = await _turno(test_session, cuerpo["public_id"])
    assert (nuevo.client_name, nuevo.client_email, nuevo.client_phone) == (
        "Cliente Panel",
        "cliente-panel@example.com",
        "5491155559001",
    )
    assert nuevo.price_amount == Decimal("10000.00")
    assert nuevo.idempotency_key == "carac-panel-repro-0001"
    nuevas = (await _auditoria(test_session))[auditoria_antes:]
    assert [(a[0], a[1]) for a in nuevas] == [
        ("status_change", "Appointment"),
        ("create", "Appointment"),
    ]
    assert nuevas[1][2]["rescheduled_from"] == turno
    eventos = (await _eventos(test_session))[eventos_antes:]
    assert [(e[0], e[1]["reason"]) for e in eventos] == [
        ("appointment.slot_released", "rescheduled")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", ["choque", "con_cobro", "inexistente"])
async def test_reprogramar_del_panel_rechazos(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    t = await _tienda(client, f"carac-prr-{caso}")
    _buzon_en_orden(None, monkeypatch)
    turno = (await _alta_panel(client, t, t.slot, f"carac-prr-{caso}-1")).json()[
        "public_id"
    ]
    otro = await _alta_panel(
        client, t, t.slot + timedelta(hours=2), f"carac-prr-{caso}-2"
    )
    assert otro.status_code == 201, otro.text
    objetivo = turno
    if caso == "con_cobro":
        await test_session.execute(
            update(Appointment)
            .where(Appointment.id == turno)
            .values(status="pending_payment")
        )
        await test_session.commit()
        esperado = (409, "PAYMENT_APPOINTMENT_REQUIRES_RELEASE")
    elif caso == "inexistente":
        objetivo = "01J00000000000000000000000"
        esperado = (404, "APPOINTMENT_NOT_FOUND")
    else:
        esperado = (409, "APPOINTMENT_CONFLICT")
    eventos_antes = await _eventos(test_session)
    estado_antes = (await _turno(test_session, turno)).status

    res = await client.patch(
        f"/appointments/{objetivo}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": f"carac-prr-{caso}-nuevo",
        },
    )

    assert (res.status_code, res.json()["error_code"]) == esperado, res.text
    assert await _eventos(test_session) == eventos_antes
    assert (await _turno(test_session, turno)).status == estado_antes
    assert await _contar(test_session, Appointment) == 2


# ---------------------------------------------------------------------------
# Liberacion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_liberar_del_panel_cuerpo_outbox_auditoria_y_orden(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "carac-panel-libera")
    _buzon_en_orden(None, monkeypatch)
    turno = (await _alta_panel(client, t, t.slot, "carac-pl-0001")).json()["public_id"]
    auditoria_antes = len(await _auditoria(test_session))
    orden = _espiar_orden(test_session, await _redis(), monkeypatch)

    res = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(t.token)
    )

    assert res.status_code == 200, res.text
    assert (res.json()["public_id"], res.json()["status"]) == (turno, "expired")
    assert orden == ["commit", "cache"], orden
    eventos = await _eventos(test_session)
    assert [e[0] for e in eventos] == [
        "appointment.released",
        "appointment.slot_released",
    ]
    assert eventos[0][1] == {
        "appointment_id": turno,
        "payment_id": None,
        "released_by": eventos[0][1]["released_by"],
    }
    assert eventos[1][1]["reason"] == "released"
    nuevas = (await _auditoria(test_session))[auditoria_antes:]
    assert [(a[0], a[2]) for a in nuevas] == [
        ("status_change", {"status": "expired", "reason": "manual_store_release"})
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", ["no_liberable", "pagado", "inexistente"])
async def test_liberar_del_panel_rechazos(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caso: str,
) -> None:
    t = await _tienda(client, f"carac-plr-{caso}")
    _buzon_en_orden(None, monkeypatch)
    turno = (await _alta_panel(client, t, t.slot, f"carac-plr-{caso}")).json()[
        "public_id"
    ]
    objetivo = turno
    if caso == "no_liberable":
        confirmado = await client.patch(
            f"/appointments/{turno}/confirm", headers=auth_headers(t.token)
        )
        assert confirmado.status_code == 200, confirmado.text
        esperado = (409, "APPOINTMENT_NOT_RELEASABLE")
    elif caso == "pagado":
        fila = await _turno(test_session, turno)
        test_session.add(
            Payment(
                store_id=fila.store_id,
                appointment_id=turno,
                amount=Decimal("2500.00"),
                status="approved",
            )
        )
        await test_session.commit()
        esperado = (409, "PAID_APPOINTMENT_NOT_RELEASABLE")
    else:
        objetivo = "01J00000000000000000000000"
        esperado = (404, "APPOINTMENT_NOT_FOUND")
    estado_antes = (await _turno(test_session, turno)).status

    res = await client.patch(
        f"/appointments/{objetivo}/release", headers=auth_headers(t.token)
    )

    assert (res.status_code, res.json()["error_code"]) == esperado, res.text
    assert await _eventos(test_session) == []
    assert (await _turno(test_session, turno)).status == estado_antes
