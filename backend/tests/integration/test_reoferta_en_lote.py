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

import modules.notifications.tasks as tasks
import modules.waitlist.tasks as waitlist_tasks
from modules.payments.jobs import process_outbox_batch
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
async def test_la_corrida_commitea_una_vez_y_manda_los_mails_despues(
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
    assert eventos == ["commit", "mail:marta@example.com"], eventos
