"""F1-18 (plan de rendimiento, R7-10; decision 23): un solo orden de locks, turno -> pago.

2026-09-24. Sintoma: el webhook de Mercado Pago lockeaba el PAGO y despues el
TURNO (``find_payment_for_webhook`` con ``FOR UPDATE`` y recien despues el
turno), mientras que liberar un turno desde el panel y el job de vencimiento
lockean TURNO y despues PAGO (``AppointmentService.release_pending``,
``PaymentRepository.get_by_appointment_locked``). Dos ordenes opuestos sobre
las mismas dos filas: un webhook y un "liberar" simultaneos se esperaban en
ciclo, Postgres abortaba uno (40P01 -> 409) y el inbox reintentaba.
``pg_stat_database.deadlocks`` = 2 en la base local.

Ahora el webhook busca el pago SIN lock (solo para saber de que turno es),
lockea el turno y despues el pago, releyendolo bajo el lock. En SQLite no hay
locks: se registra el orden de las sentencias ``FOR UPDATE`` compilandolas
para Postgres. La rafaga real la cubre ``tests/postgres/test_pg_rafaga_cobros.py``.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement

import modules.notifications.tasks as tasks
from modules.payments.model import PaymentStatus
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_pago_sobre_turno_liberado import _turno_con_sena
from tests.integration.test_payments_hardening_and_legal import (
    _approved_remote_payment,
    _stub_mercadopago,
)


# El dialecto de Postgres no esta tipado (mismo recurso que
# test_recordatorios_skip_locked.py).
_DIALECTO_PG: Any = postgresql.dialect


def _registrar_locks(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Tabla de cada ``SELECT ... FOR UPDATE``, en el orden en que se ejecuta."""
    locks: list[str] = []
    original = session.execute

    async def execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(statement, "_for_update_arg", None) is not None:
            sentencia = cast(ClauseElement, statement)
            sql = str(sentencia.compile(dialect=_DIALECTO_PG()))
            desde = re.search(r"FROM\s+(\w+)", sql)
            assert desde is not None, sql
            locks.append(desde.group(1))
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute)
    return locks


@pytest.mark.asyncio
async def test_el_webhook_lockea_el_turno_antes_que_el_pago(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    turno, pago = await _turno_con_sena(client, test_session, "f118-orden", 10)
    remoto = _approved_remote_payment(pago)

    locks = _registrar_locks(test_session, monkeypatch)
    assert await apply_mercadopago_webhook_payload(
        test_session,
        store_id=pago.store_id,
        payload={"data": remoto, "status": "approved"},
    )
    await test_session.commit()

    assert locks == ["appointments", "payments"], locks
    # Las validaciones y el efecto siguen: el pago queda acreditado.
    await test_session.refresh(pago)
    assert pago.status == PaymentStatus.APPROVED.value
    assert pago.external_payment_id == "mp-remote-1"
    assert turno.id == pago.appointment_id
