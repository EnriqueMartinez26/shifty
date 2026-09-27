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

2026-09-20, AUD2-B2-02: los dos lotes pasaron a dos fases (fase A sin lock
para hablar con Mercado Pago, fase B con lock para escribir), asi que ahora
ejecutan DOS consultas sobre la misma entidad. La que tiene que bloquear es
la de la fase B: aca se busca esa. La exclusion entre corridas solapadas la
da ademas el advisory lock de sesion (``_exclusive_job``), que es lo que
reemplaza al SKIP LOCKED durante la fase de HTTP.

2026-09-24 (revision de F1-18): la conciliacion ya no bloquea el lote de
cobros; el SKIP LOCKED paso al lock del turno de cada cobro, para respetar el
orden unico turno -> pago.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.jobs import (
    process_webhook_inbox_batch,
    reconcile_pending_payments,
)
import modules.payments.jobs as jobs
from modules.payments.model import Payment, PaymentGatewayConfig, WebhookInbox


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


def _consulta_bloqueada_del_lote(ejecutadas: list[Any], entidad: type) -> Select[Any]:
    """La SELECT ORM de la fase B: la que bloquea las filas del lote."""
    for statement in ejecutadas:
        if not isinstance(statement, Select):
            continue
        descripciones = statement.column_descriptions
        if (
            descripciones
            and descripciones[0].get("entity") is entidad
            and statement._for_update_arg is not None
        ):
            return statement
    raise AssertionError(f"el lote no bloqueo ninguna fila de {entidad.__name__}")


def _bloquea_con_skip_locked(statement: Select[Any]) -> bool:
    for_update = statement._for_update_arg
    return for_update is not None and bool(for_update.skip_locked)


@pytest.mark.asyncio
async def test_el_lote_del_inbox_toma_sus_filas_con_skip_locked(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F1-20: la fase B solo corre sobre lo que la fase A alcanzo a consultar.
    # Un evento que no es de MP no necesita consulta y la hace correr.
    test_session.add(
        WebhookInbox(
            store_id="tienda-b203", provider="otro", event_id="b203", payload={}
        )
    )
    await test_session.commit()
    ejecutadas = _espiar_sentencias(monkeypatch, test_session)

    stats = await process_webhook_inbox_batch(test_session)

    assert stats == {"processed": 1, "failed": 0, "inspected": 1}
    lote = _consulta_bloqueada_del_lote(ejecutadas, WebhookInbox)
    assert _bloquea_con_skip_locked(lote), (
        "el inbox se selecciona sin FOR UPDATE SKIP LOCKED: dos corridas "
        "solapadas del beat toman el mismo webhook (regla 8)"
    )


@pytest.mark.asyncio
async def test_la_conciliacion_no_bloquea_el_lote_de_cobros(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de F1-18 (2026-09-24): el lote de conciliacion se bloqueaba con
    ``FOR UPDATE SKIP LOCKED OF payments`` y despues el apply lockeaba el
    turno: orden pago -> turno, el opuesto al del webhook, el panel y el job de
    vencimiento. Ahora la fase B lee el lote SIN lock (la exclusion entre
    corridas es el advisory lock de ``_exclusive_job``) y cada cobro lockea su
    turno con SKIP LOCKED y despues el pago
    (``test_webhook_lockea_turno_antes_que_pago.py``).
    """
    # Revision de f2b: con la tabla vacia la fase B ni corre y el test no
    # podia fallar. Un cobro viejo pendiente la hace leer el lote.
    test_session.add(
        PaymentGatewayConfig(
            store_id="t-f118", provider="mercadopago", encrypted_access_token="x"
        )
    )
    test_session.add(
        Payment(
            store_id="t-f118",
            appointment_id="t-f118-turno",
            provider="mercadopago",
            amount=Decimal("1000"),
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    await test_session.commit()

    async def sin_respuesta(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(jobs, "_fetch_remote_payment", sin_respuesta)
    ejecutadas = _espiar_sentencias(monkeypatch, test_session)

    stats = await reconcile_pending_payments(test_session)

    assert stats == {"reconciled": 0, "failed": 0, "inspected": 1}
    # La fase B leyo el lote de cobros (sin lock).
    assert any(
        isinstance(s, Select)
        and s.column_descriptions
        and s.column_descriptions[0].get("entity") is Payment
        for s in ejecutadas
    )
    with pytest.raises(AssertionError, match="no bloqueo ninguna fila de Payment"):
        _consulta_bloqueada_del_lote(ejecutadas, Payment)
