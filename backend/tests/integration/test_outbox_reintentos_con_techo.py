"""Un mensaje del outbox que siempre falla deja de reintentarse.

2026-09-17, hallazgo B2-12: ``process_outbox_batch`` anotaba ``error`` y
dejaba ``processed_at`` en NULL, asi que el beat volvia a tomar el mensaje
cada minuto, para siempre. Una fila con payload corrupto (por ejemplo un
``slot.released`` sin ``staff_id``: ``ReleasedSlot.from_payload`` revienta)
se ordena primero por ``created_at``, ocupa lugar del ``limit=100`` en cada
corrida y ``pending_with_error`` crece sin que nadie lo cierre.
``WebhookInbox`` ya tenia el contador y el techo (regla 7); el outbox no.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.jobs import process_outbox_batch
from modules.payments.model import WEBHOOK_INBOX_MAX_ATTEMPTS, OutboxMessage
from modules.waitlist.events import EVENT_SLOT_RELEASED


def _mensaje_envenenado() -> OutboxMessage:
    # Sin staff_id / starts_at / ends_at: from_payload levanta KeyError.
    return OutboxMessage(
        store_id="tienda-outbox", event_type=EVENT_SLOT_RELEASED, payload={}
    )


@pytest.mark.asyncio
async def test_el_mensaje_que_siempre_falla_se_abandona_al_agotar_los_intentos(
    test_session: AsyncSession,
) -> None:
    mensaje = _mensaje_envenenado()
    test_session.add(mensaje)
    await test_session.commit()

    for _ in range(WEBHOOK_INBOX_MAX_ATTEMPTS):
        await process_outbox_batch(test_session)

    await test_session.refresh(mensaje)
    assert mensaje.processed_at is not None, "debe dejar de reintentarse"
    assert mensaje.attempts == WEBHOOK_INBOX_MAX_ATTEMPTS
    assert mensaje.error

    # Y ya no entra en el lote siguiente.
    siguiente = await process_outbox_batch(test_session)
    assert siguiente["inspected"] == 0


@pytest.mark.asyncio
async def test_mientras_queden_intentos_el_mensaje_sigue_pendiente(
    test_session: AsyncSession,
) -> None:
    mensaje = _mensaje_envenenado()
    test_session.add(mensaje)
    await test_session.commit()

    resultado = await process_outbox_batch(test_session)

    await test_session.refresh(mensaje)
    assert resultado["failed"] == 1
    assert mensaje.attempts == 1
    assert mensaje.processed_at is None, "un fallo transitorio se reintenta"


def test_el_lote_del_outbox_sigue_tomando_filas_con_skip_locked() -> None:
    """Guarda viva (regla 8): el contador no reemplaza al FOR UPDATE SKIP LOCKED.

    Sin el lock, dos corridas solapadas del beat tomarian el mismo mensaje y
    ``attempts`` subiria dos veces por intento (ademas de duplicar avisos).
    """
    fuente = inspect.getsource(process_outbox_batch)
    assert ".with_for_update(skip_locked=True)" in fuente
