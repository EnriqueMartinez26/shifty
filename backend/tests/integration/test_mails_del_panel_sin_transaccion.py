"""Los mails del panel salen por el outbox, no dentro del request.

2026-09-24, F1-05 (R8-05): en ``AppointmentService.book`` el mail iba ANTES
de ``invalidate_availability``, y ``confirm``, ``complete`` y ``reschedule``
mandaban SMTP en el request (hasta 10 s por operacion) con la conexion de la
base tomada.

2026-09-24, F2-02 (R2-01): el panel ya no manda nada en el request. Reservar,
confirmar, completar y reprogramar publican un evento en el outbox
(``appointment.booked_by_panel``, ``appointment.confirmed``,
``appointment.completed``, ``appointment.rescheduled``) en la MISMA
transaccion que el cambio de estado: si el cambio se commitea, el aviso
existe; si no, tampoco. El lote del outbox (cada 20 s) relee el turno y manda
despues de su commit, con el presupuesto y el diferido de F2-03. Se eligio el
outbox y no una tarea de Celery porque es durable (sin broker en el camino del
request, sin mail perdido si el broker esta caido) y reintenta lo diferido;
el costo es hasta un tick de demora, aceptable para un aviso del panel.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.appointments.service as appointments_service
import modules.notifications.tasks as tasks
from core.availability_cache import invalidate_availability
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


def _escuchar(engine: AsyncEngine, linea: list[str]) -> tuple[Any, Any]:
    """Anota escrituras de turnos y del outbox, y cada commit."""

    def sql(_conn: Any, _cursor: Any, statement: str, *args: Any) -> None:
        texto = " ".join(statement.split()).lower()
        for tabla in ("appointments", "outbox_messages"):
            if texto.startswith((f"insert into {tabla}", f"update {tabla}")):
                linea.append(tabla)

    def commit(*args: Any, **kwargs: Any) -> None:
        linea.append("commit")

    event.listen(engine.sync_engine, "before_cursor_execute", sql)
    event.listen(engine.sync_engine, "commit", commit)
    return sql, commit


def _dejar_de_escuchar(engine: AsyncEngine, sql: Any, commit: Any) -> None:
    event.remove(engine.sync_engine, "before_cursor_execute", sql)
    event.remove(engine.sync_engine, "commit", commit)


def _espiar_invalidacion(monkeypatch: pytest.MonkeyPatch, linea: list[str]) -> None:
    invalidar_original = invalidate_availability

    async def invalidar(*args: Any, **kwargs: Any) -> None:
        linea.append("invalidar")
        await invalidar_original(*args, **kwargs)

    monkeypatch.setattr(appointments_service, "invalidate_availability", invalidar)


async def _pedir(engine: AsyncEngine, linea: list[str], pedido: Any) -> Any:
    linea.clear()
    sql, commit = _escuchar(engine, linea)
    try:
        return await pedido()
    finally:
        _dejar_de_escuchar(engine, sql, commit)


def _evento_en_la_transaccion_del_turno(linea: list[str]) -> None:
    """El evento y el turno se escriben en la misma transaccion (el primer
    commit del request los lleva a los dos; el orden entre ellos lo decide el
    flush)."""
    assert "commit" in linea, linea
    transaccion = linea[: linea.index("commit")]
    assert "outbox_messages" in transaccion, linea
    assert "appointments" in transaccion, linea


async def _eventos(session: AsyncSession, tipo: str) -> list[OutboxMessage]:
    return list(
        (
            await session.execute(
                select(OutboxMessage).where(OutboxMessage.event_type == tipo)
            )
        )
        .scalars()
        .all()
    )


async def _agenda(client: AsyncClient, slug: str) -> tuple[str, str, str, datetime]:
    _store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = (datetime.now(timezone.utc) + timedelta(days=6)).replace(
        minute=0, second=0, microsecond=0
    )
    await add_staff_schedule(client, token, staff, target_date=dia)
    return token, servicio, staff, dia


async def _turno(
    client: AsyncClient, token: str, servicio: str, staff: str, cuando: datetime
) -> Any:
    return await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": cuando.isoformat(),
            "idempotency_key": f"f202-turno-{cuando.hour:02d}",
        },
    )


@pytest.mark.asyncio
async def test_reservar_desde_el_panel_publica_el_aviso_y_no_manda_en_el_request(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    linea: list[str] = []
    _espiar_invalidacion(monkeypatch, linea)
    token, servicio, staff, dia = await _agenda(client, "f202-book")

    async def reservar() -> Any:
        return await _turno(client, token, servicio, staff, dia.replace(hour=10))

    res = await _pedir(test_engine, linea, reservar)

    assert res.status_code == 201, res.text
    assert buzon.enviados == [], "el request del panel no manda SMTP"
    _evento_en_la_transaccion_del_turno(linea)
    # El cupo se invalida despues del commit del turno.
    assert linea.index("invalidar") > linea.index("commit"), linea
    [evento] = await _eventos(test_session, "appointment.booked_by_panel")
    assert evento.payload["appointment_id"] == res.json()["public_id"]
    assert evento.store_id is not None

    await process_outbox_batch(test_session)

    assert [(to, asunto.split(" - ")[0]) for to, asunto, _ in buzon.enviados] == [
        ("f202-book@t.com", "Turno confirmado")
    ]


@pytest.mark.asyncio
async def test_confirmar_completar_y_reprogramar_publican_su_aviso_y_el_lote_lo_manda(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    linea: list[str] = []
    token, servicio, staff, dia = await _agenda(client, "f202-estados")
    turnos = []
    for hora in (10, 11):
        res = await _turno(client, token, servicio, staff, dia.replace(hour=hora))
        assert res.status_code == 201, res.text
        turnos.append(res.json()["public_id"])
    await process_outbox_batch(test_session)
    buzon.enviados.clear()
    headers = auth_headers(token)

    casos = [
        ("confirm", turnos[0], None, "appointment.confirmed", "Turno confirmado"),
        ("complete", turnos[0], None, "appointment.completed", "Gracias por tu visita"),
        (
            "reschedule",
            turnos[1],
            {
                "new_starts_at": dia.replace(hour=12).isoformat(),
                "idempotency_key": "f202-estados-reprog",
            },
            "appointment.rescheduled",
            "Te movimos el turno",
        ),
    ]
    for accion, turno, cuerpo, tipo, asunto in casos:

        async def pedir(
            accion: str = accion, turno: str = turno, cuerpo: Any = cuerpo
        ) -> Any:
            return await client.patch(
                f"/appointments/{turno}/{accion}", headers=headers, json=cuerpo
            )

        res = await _pedir(test_engine, linea, pedir)
        assert res.status_code == 200, res.text
        assert buzon.enviados == [], f"{accion}: mando SMTP en el request"
        _evento_en_la_transaccion_del_turno(linea)
        [evento] = await _eventos(test_session, tipo)
        assert evento.payload["appointment_id"] == res.json()["public_id"], accion

        await process_outbox_batch(test_session)

        assert [a.split(" - ")[0] for _, a, _ in buzon.enviados] == [asunto], accion
        buzon.enviados.clear()


@pytest.mark.asyncio
async def test_el_lote_no_confirma_un_turno_que_se_cancelo_antes_del_tick(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El lote relee el turno: entre el evento y el tick pudo cambiar."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    token, servicio, staff, dia = await _agenda(client, "f202-cancelado")
    res = await _turno(client, token, servicio, staff, dia.replace(hour=10))
    turno = res.json()["public_id"]
    headers = auth_headers(token)
    confirmar = await client.patch(f"/appointments/{turno}/confirm", headers=headers)
    assert confirmar.status_code == 200, confirmar.text
    cancelar = await client.patch(f"/appointments/{turno}/cancel", headers=headers)
    assert cancelar.status_code == 200, cancelar.text

    await process_outbox_batch(test_session)

    assert buzon.enviados == []


@pytest.mark.asyncio
async def test_el_email_del_evento_pisa_el_del_turno_incluso_si_es_nulo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La reserva desde la lista de espera avisa al email que dejo esa persona
    (``email`` en el payload), y a nadie si no dejo uno: sin la clave, el del
    turno."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    token, servicio, staff, dia = await _agenda(client, "f202-email")
    res = await _turno(client, token, servicio, staff, dia.replace(hour=10))
    turno = res.json()["public_id"]
    confirmar = await client.patch(
        f"/appointments/{turno}/confirm", headers=auth_headers(token)
    )
    assert confirmar.status_code == 200, confirmar.text
    await process_outbox_batch(test_session)
    buzon.enviados.clear()
    [evento] = await _eventos(test_session, "appointment.confirmed")
    for email in (None, "lista@example.com"):
        test_session.add(
            OutboxMessage(
                store_id=evento.store_id,
                event_type="appointment.confirmed",
                payload={"appointment_id": turno, "email": email},
            )
        )
    await test_session.commit()

    await process_outbox_batch(test_session)

    assert [to for to, _a, _c in buzon.enviados] == ["lista@example.com"]
