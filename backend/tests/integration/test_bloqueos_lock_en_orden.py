"""El alta de bloqueos lockea a los profesionales en orden total (por id).

Seguimiento S-11 (2026-09-19). ``AppointmentBlockService.create_blocks``
tomaba ``FOR UPDATE`` de a un profesional, en el orden en que los devolvia
``_staff_for`` (sin ``ORDER BY``: el que elija el planner). Dos cierres de
tienda simultaneos podian lockear los mismos profesionales en orden distinto
y terminar en deadlock. Ahora es UNA sentencia
``SELECT ... WHERE id IN (...) ORDER BY id FOR UPDATE``: Postgres toma los
locks en el orden de salida, asi que dos altas no se cruzan.

En SQLite no hay locks de fila: aca se verifica la sentencia. La carrera real
esta en tests/postgres/test_pg_bloqueos_lock_en_orden.py.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_caracterizacion_alta_publica import _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
)


@pytest.mark.asyncio
async def test_el_cierre_de_tienda_lockea_a_todos_en_una_sentencia_ordenada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "lock-orden")
    for i in range(2):
        await create_staff(client, t.token, t.service, email=f"pro{i}@lock-orden.com")

    locks: list[str] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        sql = str(statement)
        if "FROM staff" in sql and "FOR UPDATE" in sql:
            locks.append(sql)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    res = await client.post(
        "/appointment-blocks/store-wide",
        headers=auth_headers(t.token),
        json={
            "starts_at": t.slot.isoformat(),
            "ends_at": (t.slot + timedelta(hours=1)).isoformat(),
            "reason": "Feriado",
        },
    )
    monkeypatch.undo()

    assert res.status_code == 201, res.text
    assert res.json()["blocked_staff"] == 3
    assert len(locks) == 1, locks
    assert " IN (" in locks[0] and "ORDER BY staff.id" in locks[0], locks[0]
