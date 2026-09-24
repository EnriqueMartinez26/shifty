"""F2-03 (plan de rendimiento, R9-06, 2026-09-24): el outbox no tira mails.

Sintoma: el despacho post-commit del lote tiene presupuesto
(``OUTBOX_EMAIL_BUDGET_SECONDS``, por debajo del timeout idle del rol) y lo
que no entraba se anotaba con ``register_failure`` como perdido: con una
rafaga (100 eventos de 2 mails cada uno y un SMTP de 1 s por mail) se
perdian mas de la mitad de los mails, cada tick, sin reintento posible
porque el evento ya estaba procesado y reprocesarlo duplicaba la
notificacion in-app.

Correccion: cada mail es su propia fila ``email.send`` del outbox, escrita en
la MISMA transaccion del lote (antes del commit). El despacho reclama las
filas de a una (``processed_at`` + commit, ``SKIP LOCKED``) y recien despues
manda; lo que el presupuesto no alcanza sigue pendiente y sale en el tick
siguiente (20 s). ``processed_at`` nunca se reabre: ni el del evento ni el de
un mail ya reclamado.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.jobs as jobs
from modules.notifications.model import Notification, NotificationType
from modules.payments.model import OutboxMessage
from modules.users.model import User

TIENDA = "tienda-f2-03"


class _Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def monotonic(self) -> float:
        return self.ahora


async def _tienda_con_dos_admins(session: AsyncSession) -> None:
    for indice in (1, 2):
        session.add(
            User(
                email=f"duenio{indice}@example.com",
                hashed_password="x",
                role="admin",
                store_id=TIENDA,
                is_active=True,
            )
        )
    await session.commit()


def _eventos(cantidad: int) -> list[OutboxMessage]:
    """Eventos que generan una notificacion y un aviso por administrador."""
    return [
        OutboxMessage(
            store_id=TIENDA,
            event_type=NotificationType.SUBSCRIPTION_EXPIRING.value,
            payload={"days_left": 3, "plan_name": f"Plan {indice}"},
        )
        for indice in range(cantidad)
    ]


async def _filas(session: AsyncSession) -> list[OutboxMessage]:
    return list(
        (
            await session.execute(
                select(OutboxMessage).execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_una_rafaga_que_excede_el_presupuesto_sale_entera_en_los_ticks_siguientes(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    reloj = _Reloj()
    monkeypatch.setattr(jobs, "time", SimpleNamespace(monotonic=reloj.monotonic))
    enviados: list[tuple[str, str]] = []
    por_tick: list[int] = []

    async def smtp_de_un_segundo(
        *, email: str, title: str, body: str | None = None, smtp: Any = None
    ) -> dict[str, str]:
        reloj.ahora += 1.0
        enviados.append((email, body or ""))
        return {"status": "sent"}

    monkeypatch.setattr(jobs, "send_store_notification_email", smtp_de_un_segundo)
    await _tienda_con_dos_admins(test_session)
    for evento in _eventos(100):
        test_session.add(evento)
    await test_session.commit()

    for _tick in range(20):
        antes = len(enviados)
        await jobs.process_outbox_batch(test_session, limit=25)
        por_tick.append(len(enviados) - antes)
        pendientes = [f for f in await _filas(test_session) if f.processed_at is None]
        if not pendientes:
            break

    # Ningun mail perdido ni repetido: 100 eventos x 2 administradores.
    assert len(enviados) == 200, por_tick
    assert len(set(enviados)) == 200, "un mail salio dos veces"
    # El presupuesto se respeto en cada tick: lo que no entro, espero.
    assert max(por_tick) <= jobs.OUTBOX_EMAIL_BUDGET_SECONDS, por_tick
    assert len(por_tick) > 200 // jobs.OUTBOX_EMAIL_BUDGET_SECONDS, por_tick
    filas = await _filas(test_session)
    assert all(f.processed_at is not None for f in filas)
    assert all(f.attempts == 0 and f.error is None for f in filas), [
        (f.event_type, f.attempts, f.error) for f in filas if f.attempts or f.error
    ]
    # Cada evento genero su notificacion una sola vez: nada se reproceso.
    notificaciones = (await test_session.execute(select(Notification))).scalars().all()
    assert len(notificaciones) == 100


@pytest.mark.asyncio
async def test_los_mails_quedan_en_la_base_con_el_commit_del_lote(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El worker muere despues del commit del lote y antes de mandar nada: los
    mails no se pierden, los manda la corrida siguiente."""

    class ProcesoMuerto(BaseException):
        pass

    @asynccontextmanager
    async def smtp_que_mata_el_proceso() -> AsyncIterator[object]:
        raise ProcesoMuerto()
        yield object()  # pragma: no cover

    enviados: list[str] = []

    async def aviso(
        *, email: str, title: str, body: str | None = None, smtp: Any = None
    ) -> dict[str, str]:
        enviados.append(email)
        return {"status": "sent"}

    monkeypatch.setattr(jobs, "send_store_notification_email", aviso)
    await _tienda_con_dos_admins(test_session)
    for evento in _eventos(1):
        test_session.add(evento)
    await test_session.commit()

    monkeypatch.setattr(jobs, "smtp_session", smtp_que_mata_el_proceso)
    with pytest.raises(ProcesoMuerto):
        await jobs.process_outbox_batch(test_session)
    await test_session.rollback()
    assert enviados == []

    monkeypatch.undo()
    monkeypatch.setattr(jobs, "send_store_notification_email", aviso)
    await jobs.process_outbox_batch(test_session)

    assert sorted(enviados) == ["duenio1@example.com", "duenio2@example.com"]
    notificaciones = (await test_session.execute(select(Notification))).scalars().all()
    assert len(notificaciones) == 1, "el evento no se reproceso"
