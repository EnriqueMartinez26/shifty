"""La re-oferta de la lista de espera procesa las vencidas en lotes acotados.

Audit B1-16 (2026-09-18), regla 12 y bloque "Lista de espera" de CLAUDE.md.
Sintoma: ``expire_lapsed_offers`` tomaba TODAS las ofertas vencidas con
``FOR UPDATE SKIP LOCKED`` y sin ``LIMIT`` ni orden, y por cada una hacia >=5
consultas (re-ofrecer el cupo) dentro de la misma transaccion: cuanto mas
crece la cola, mas tiempo quedan las filas tomadas y mas cerca del
``task_time_limit`` de Celery. Ahora el lote tiene tope y orden determinista
(``offer_expires_at``); el resto va en la corrida siguiente.

Las guardas que se conservan y se prueban aca: ``SKIP LOCKED`` en el lote
(regla 8), un solo commit por corrida y ningun mail dentro de la transaccion
(los devuelve ``pending_emails`` y salen despues del commit). La carrera real
entre dos corridas esta en tests/postgres/test_pg_lista_de_espera_reoferta.py.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
import modules.notifications.tasks as tasks
import modules.waitlist.tasks as waitlist_tasks
from modules.payments.jobs import EVENT_EMAIL_SEND, process_outbox_batch
from modules.payments.model import OutboxMessage
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import expire_lapsed_offers
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_lista_de_espera import _alta, _reservar, _tienda
from tests.integration.test_mails_al_cliente import Buzon


async def _tres_ofertas_vencidas(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[list[str], datetime]:
    """Tres entradas con oferta vencida, cada una sobre su propio cupo.

    Vencen al reves del orden de alta (la ultima anotada vencio primero, hace
    3 minutos), para que el orden del lote no salga gratis del orden de
    insercion. Cada una
    espera en un dia distinto para que la re-oferta de un cupo no le toque a
    otra de las tres (el test mira el tope del lote, no el pase de mano).
    """
    store, _token, service, staff, slot = await _tienda(client, slug)
    ids: list[str] = []
    for i in range(3):
        alta = await client.post(
            "/public/waitlist",
            json=_alta(
                store,
                service,
                slot + timedelta(days=i),
                client_name=f"Espera {i}",
                client_phone=f"+54911555{i:05d}",
                client_email=f"espera{i}-{slug}@example.com",
            ),
        )
        assert alta.status_code == 201, alta.text
        ids.append(str(alta.json()["public_id"]))

    ahora = datetime.now(timezone.utc)
    entradas = {
        e.id: e
        for e in (
            await session.execute(
                select(WaitlistEntry).where(WaitlistEntry.id.in_(ids))
            )
        ).scalars()
    }
    for i, entry_id in enumerate(ids):
        entrada = entradas[entry_id]
        entrada.status = "offered"
        entrada.notified_at = ahora - timedelta(minutes=15)
        entrada.offer_expires_at = ahora - timedelta(minutes=1 + i)
        entrada.offered_staff_id = staff
        entrada.offered_starts_at = slot + timedelta(days=i)
        entrada.offered_ends_at = slot + timedelta(days=i, minutes=30)
    await session.commit()
    return ids, ahora


async def _estados(session: AsyncSession, ids: list[str]) -> list[str]:
    session.expire_all()
    filas = {
        e.id: e.status
        for e in (
            await session.execute(
                select(WaitlistEntry).where(WaitlistEntry.id.in_(ids))
            )
        ).scalars()
    }
    return [filas[i] for i in ids]


@pytest.mark.asyncio
async def test_el_lote_de_vencidas_tiene_tope_orden_y_skip_locked(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids, ahora = await _tres_ofertas_vencidas(client, test_session, "lote-espera")

    consultas: list[Any] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        consultas.append(statement)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    primera = await expire_lapsed_offers(test_session, now=ahora, limit=2)
    await test_session.commit()
    monkeypatch.undo()

    # Tope: dos por corrida, las que vencieron primero (las dos ultimas).
    assert primera.lapsed == 2
    assert await _estados(test_session, ids) == ["offered", "waiting", "waiting"]

    # La primera consulta es el lote de vencidas: LIMIT, ORDER BY y la guarda
    # de la regla 8 (FOR UPDATE SKIP LOCKED) intactos.
    lote = consultas[0]
    assert lote._limit_clause is not None, "el lote de vencidas no tiene tope"
    assert "offer_expires_at" in str(lote._order_by_clause), "sin orden determinista"
    assert lote._for_update_arg is not None and lote._for_update_arg.skip_locked

    # El resto va en la corrida siguiente.
    segunda = await expire_lapsed_offers(test_session, now=ahora, limit=2)
    await test_session.commit()
    assert segunda.lapsed == 1
    assert await _estados(test_session, ids) == ["waiting", "waiting", "waiting"]


@pytest.mark.asyncio
async def test_la_corrida_por_defecto_tambien_tiene_tope(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin pasar ``limit`` (como la llama el beat) el lote igual esta acotado."""
    _ids, ahora = await _tres_ofertas_vencidas(client, test_session, "lote-defecto")
    consultas: list[Any] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        consultas.append(statement)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    resultado = await expire_lapsed_offers(test_session, now=ahora)
    monkeypatch.undo()
    await test_session.rollback()

    assert resultado.lapsed == 3
    assert consultas[0]._limit_clause is not None, "el lote de vencidas no tiene tope"


@pytest.mark.asyncio
async def test_la_corrida_persiste_el_mail_y_el_dispatch_va_despues_del_commit(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda del bloque "Lista de espera": ningun mail dentro de la transaccion."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "lote-mails")
    primera = await client.post("/public/waitlist", json=_alta(store, service, slot))
    segunda = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot,
            client_name="Marta",
            client_phone="+5491155550102",
            client_email="marta@example.com",
        ),
    )
    assert primera.status_code == 201 and segunda.status_code == 201
    pid = await _reservar(client, store, service, staff, slot, "lote-mails-00001")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text
    await process_outbox_batch(test_session)  # la oferta va a Lucia

    eventos: list[str] = []
    commit_original = test_session.commit

    async def commit_espiado() -> None:
        filas_email: list[OutboxMessage] = []
        for fila in test_session.new:
            if not isinstance(fila, OutboxMessage) or fila.event_type != "email.send":
                continue
            payload = fila.payload
            if not isinstance(payload, dict):
                continue
            argumentos = payload.get("args")
            if (
                isinstance(argumentos, dict)
                and argumentos.get("email") == "marta@example.com"
            ):
                filas_email.append(fila)
        assert len(filas_email) == 1, filas_email
        assert any(
            isinstance(entrada, WaitlistEntry) and entrada.status == "offered"
            for entrada in test_session.dirty
        )
        eventos.append("commit")
        await commit_original()

    async def enviar_espiado(
        to: str, subject: str, body: str, smtp: Any = None
    ) -> bool:
        eventos.append(f"mail:{to}")
        return await buzon(to, subject, body)

    @asynccontextmanager
    async def sesion_de_prueba() -> AsyncIterator[AsyncSession]:
        yield test_session

    monkeypatch.setattr(test_session, "commit", commit_espiado)
    monkeypatch.setattr(tasks, "_send_email", enviar_espiado)
    monkeypatch.setattr(waitlist_tasks, "AsyncSessionFactory", sesion_de_prueba)

    contadores = await waitlist_tasks.process_waitlist_offers_once(
        now=datetime.now(timezone.utc) + timedelta(minutes=30)
    )

    assert contadores["reoffered"] == 1, contadores
    assert eventos == ["commit"], eventos

    await process_outbox_batch(test_session, incluir_vencimientos=False)

    assert eventos == ["commit", "mail:marta@example.com"], eventos


@pytest.mark.parametrize("reofertar", [True, False], ids=["reoferta", "solo-expirada"])
@pytest.mark.asyncio
async def test_retry_de_oferta_expirada_no_manda_datos_viejos_ni_muta_estado(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    reofertar: bool,
) -> None:
    """Un retry pre-DATA no manda A tras vencerla, aunque el outbox siga pendiente."""
    slug = f"retry-oferta-{'b' if reofertar else 'expirada'}"
    email_a = f"lucia-{slug}@example.com"
    email_b = f"marta-{slug}@example.com"
    fallar_a = True
    enviados: list[tuple[str, str, str]] = []

    async def sink(to: str, subject: str, body: str, smtp: Any = None) -> bool:
        nonlocal fallar_a
        if to == email_a and fallar_a:
            fallar_a = False
            smtp.last_delivery_retryable = True
            return False
        enviados.append((to, subject, body))
        return True

    monkeypatch.setattr(tasks, "_send_email", sink)
    store, token, service, staff, slot = await _tienda(client, slug)
    entry_ids: list[str] = []
    for nombre, telefono, email in (
        ("Lucia", "+5491155550121", email_a),
        ("Marta", "+5491155550122", email_b),
    ):
        alta = await client.post(
            "/public/waitlist",
            json=_alta(
                store,
                service,
                slot,
                client_name=nombre,
                client_phone=telefono,
                client_email=email,
            ),
        )
        assert alta.status_code == 201, alta.text
        entry_ids.append(str(alta.json()["public_id"]))

    appointment_id = await _reservar(
        client, store, service, staff, slot, f"{slug}-booking"
    )
    cancelar = await client.patch(
        f"/appointments/{appointment_id}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text
    await process_outbox_batch(test_session, incluir_vencimientos=False)
    assert not fallar_a, "la primera oferta de A no tuvo fallo pre-DATA"

    async def fila_de_mail(email: str) -> OutboxMessage:
        filas = list(
            (
                await test_session.execute(
                    select(OutboxMessage).where(
                        OutboxMessage.event_type == EVENT_EMAIL_SEND
                    )
                )
            )
            .scalars()
            .all()
        )
        matches = [
            fila
            for fila in filas
            if (fila.payload.get("args") or {}).get("email") == email
        ]
        assert len(matches) == 1, matches
        return matches[0]

    mail_a = await fila_de_mail(email_a)
    assert mail_a.attempts == 1
    assert mail_a.processed_at is None
    assert email_a not in [destino for destino, _asunto, _cuerpo in enviados]
    entry_a_id = str(mail_a.payload["guard"]["entry_id"])
    entry_a = await test_session.get(WaitlistEntry, entry_a_id)
    assert entry_a is not None
    entry_b_id = entry_ids[1]

    # El outbox conserva el intento A; hacemos vencer esa oferta antes del retry.
    entry_a.offer_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await test_session.commit()
    if reofertar:

        @asynccontextmanager
        async def sesion_de_prueba() -> AsyncIterator[AsyncSession]:
            yield test_session

        monkeypatch.setattr(waitlist_tasks, "AsyncSessionFactory", sesion_de_prueba)
        resultado = await waitlist_tasks.process_waitlist_offers_once(
            now=datetime.now(timezone.utc)
        )
        assert resultado["reoffered"] == 1, resultado

    test_session.expire_all()

    async def estado_lista() -> list[tuple[Any, ...]]:
        return list(
            (
                await test_session.execute(
                    select(
                        WaitlistEntry.id,
                        WaitlistEntry.status,
                        WaitlistEntry.offer_expires_at,
                        WaitlistEntry.offered_staff_id,
                        WaitlistEntry.offered_starts_at,
                        WaitlistEntry.offered_ends_at,
                        WaitlistEntry.lapsed_offers,
                    )
                    .where(WaitlistEntry.id.in_([entry_a_id, entry_b_id]))
                    .order_by(WaitlistEntry.id)
                )
            ).all()
        )

    estado_antes = await estado_lista()
    booking_antes = (
        await test_session.execute(
            select(Appointment.status).where(Appointment.id == appointment_id)
        )
    ).scalar_one()

    # Re-dispatch claims A first, marks it terminal as stale, then sends B only
    # when the expiration path handed the slot to B.
    await process_outbox_batch(test_session, incluir_vencimientos=False)

    test_session.expire_all()
    estado_despues = await estado_lista()
    booking_despues = (
        await test_session.execute(
            select(Appointment.status).where(Appointment.id == appointment_id)
        )
    ).scalar_one()
    mail_a = await fila_de_mail(email_a)
    assert mail_a.processed_at is not None
    assert mail_a.error == "waitlist_offer_stale"
    assert mail_a.attempts == 1
    assert estado_despues == estado_antes
    assert booking_despues == booking_antes
    assert email_a not in [destino for destino, _asunto, _cuerpo in enviados]
    assert (email_b in [destino for destino, _asunto, _cuerpo in enviados]) is reofertar
    if reofertar:
        assert any(
            destino == email_b and "Marta" in cuerpo
            for destino, _asunto, cuerpo in enviados
        )


@pytest.mark.asyncio
async def test_la_reoferta_saltea_a_quien_no_tiene_email(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FF-25 (2026-10-01): la re-oferta le pasaba el cupo a una entrada sin email.

    Sintoma: al vencer una oferta, ``expire_lapsed_offers`` reusa
    ``offer_released_slot``, que tomaba la siguiente entrada aunque no tuviera
    email: quedaba ``offered`` sin aviso y le gastaba ``lapsed_offers``. Ahora
    la saltea y el cupo pasa a la siguiente con email entregable
    (D-20260930-11); la salteada sigue esperando sin gastar ofertas.
    """
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, token, service, staff, slot = await _tienda(client, "reoferta-sin-email")
    ids: list[str] = []
    for nombre, telefono, email in (
        ("Lucia", "+5491155550121", "lucia-reoferta@example.com"),
        ("Sin Email", "+5491155550122", "sin-email-reoferta@example.com"),
        ("Marta", "+5491155550123", "marta-reoferta@example.com"),
    ):
        alta = await client.post(
            "/public/waitlist",
            json=_alta(
                store,
                service,
                slot,
                client_name=nombre,
                client_phone=telefono,
                client_email=email,
            ),
        )
        assert alta.status_code == 201, alta.text
        ids.append(str(alta.json()["public_id"]))
    # Desde el 2026-10-14 el alta publica exige email (decision de Mateo); una
    # entrada sin email es una anterior a ese cambio: se fuerza en la fila.
    sin_email = (
        await test_session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == ids[1])
        )
    ).scalar_one()
    sin_email.client_email = None
    await test_session.commit()
    pid = await _reservar(client, store, service, staff, slot, "reoferta-sinmail1")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text
    await process_outbox_batch(test_session)  # la oferta va a Lucia
    await test_session.commit()
    assert await _estados(test_session, ids) == ["offered", "waiting", "waiting"]

    resumen = await expire_lapsed_offers(
        test_session, now=datetime.now(timezone.utc) + timedelta(minutes=30)
    )
    await test_session.commit()

    assert resumen.lapsed == 1 and resumen.reoffered == 1
    assert [p.email for p in resumen.pending_emails] == ["marta-reoferta@example.com"]
    assert await _estados(test_session, ids) == ["waiting", "waiting", "offered"]
    salteada = (
        await test_session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == ids[1])
        )
    ).scalar_one()
    assert salteada.lapsed_offers == 0
    assert salteada.notified_at is None
