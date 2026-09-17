"""Los lotes del inbox y de conciliacion toman sus filas con SKIP LOCKED.

2026-09-16, hallazgo B2-03: ``process_webhook_inbox_batch`` y
``reconcile_pending_payments`` seleccionaban el lote sin bloqueo, a diferencia
del outbox. Las dos tareas estan en el beat (cada minuto / cada 5) y cada
item hace una o dos llamadas HTTP a Mercado Pago, asi que una corrida puede
durar mas que su intervalo. Sintoma: la corrida de las 10:01 tomaba las mismas
filas que la de las 10:00 todavia en curso, repetia el ``fetch`` a MP por
evento y sumaba ``attempts`` dos veces por el mismo webhook (regla 8).

SQLite ignora ``FOR UPDATE``, asi que aca se verifica la sentencia que arma
cada lote; la concurrencia real vive en ``tests/postgres``.
"""

from typing import Any

import pytest
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.jobs import (
    process_webhook_inbox_batch,
    reconcile_pending_payments,
)
from modules.payments.model import Payment, WebhookInbox


def _espiar_sentencias(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> list[Any]:
    ejecutadas: list[Any] = []
    ejecutar = session.execute

    async def execute_espia(statement: Any, *args: Any, **kwargs: Any) -> Any:
        ejecutadas.append(statement)
        return await ejecutar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute_espia)
    return ejecutadas


def _consulta_del_lote(ejecutadas: list[Any], entidad: type) -> Select[Any]:
    """La SELECT ORM cuya primera entidad es la fila del lote."""
    for statement in ejecutadas:
        if not isinstance(statement, Select):
            continue
        descripciones = statement.column_descriptions
        if descripciones and descripciones[0].get("entity") is entidad:
            return statement
    raise AssertionError(f"el lote no consulto {entidad.__name__}")


def _bloquea_con_skip_locked(statement: Select[Any]) -> bool:
    for_update = statement._for_update_arg
    return for_update is not None and bool(for_update.skip_locked)


@pytest.mark.asyncio
async def test_el_lote_del_inbox_toma_sus_filas_con_skip_locked(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ejecutadas = _espiar_sentencias(monkeypatch, test_session)

    stats = await process_webhook_inbox_batch(test_session)

    assert stats == {"processed": 0, "failed": 0, "inspected": 0}
    lote = _consulta_del_lote(ejecutadas, WebhookInbox)
    assert _bloquea_con_skip_locked(lote), (
        "el inbox se selecciona sin FOR UPDATE SKIP LOCKED: dos corridas "
        "solapadas del beat toman el mismo webhook (regla 8)"
    )


@pytest.mark.asyncio
async def test_el_lote_de_conciliacion_toma_sus_cobros_con_skip_locked(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ejecutadas = _espiar_sentencias(monkeypatch, test_session)

    stats = await reconcile_pending_payments(test_session)

    assert stats == {"reconciled": 0, "failed": 0, "inspected": 0}
    lote = _consulta_del_lote(ejecutadas, Payment)
    assert _bloquea_con_skip_locked(lote), (
        "la conciliacion selecciona sin FOR UPDATE SKIP LOCKED: dos corridas "
        "solapadas consultan dos veces a Mercado Pago por el mismo cobro"
    )
    # La consulta hace JOIN con payment_gateway_configs: se bloquea solo la
    # fila del cobro, no la configuracion de la tienda.
    for_update = lote._for_update_arg
    assert for_update is not None and for_update.of is not None
