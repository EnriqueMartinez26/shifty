"""El lock pesimista del turno tambien filtra por tienda.

Auditoria 2, AUD2-B1-09 (2026-09-20). Sintoma: `lock_by_public_id` recibia
`store_id` y NO lo usaba: el `SELECT ... FOR UPDATE` de los cinco cambios de
estado del panel (cancel, confirm, complete, mark_absent, release_pending) se
tomaba solo por `id`. Con RLS puesto la fila ajena no es visible, asi que no
hay fuga, pero el filtro `store_id` que §2 de CLAUDE.md exige como defensa en
profundidad no estaba, y un parametro que se ignora invita a asumir que
protege. En SQLite -donde corre toda la suite de integracion- no hay RLS, que
es justo el tipo de hueco que la suite no ve.

Aca se verifica la sentencia emitida: en SQLite el `FOR UPDATE` es un no-op y
no hay forma de observar el lock. La consulta tiene que llevar los dos
predicados, igual que el `get_by_public_id` que viene despues.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon


@pytest.mark.asyncio
async def test_el_lock_del_turno_lleva_id_y_store_id(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "lock-tienda")
    reserva = await client.post(
        "/public/appointments", json=_reserva(t, "lock-tienda-0001")
    )
    assert reserva.status_code == 201, reserva.text

    locks: list[str] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        sql = str(statement)
        if "FROM appointments" in sql and "FOR UPDATE" in sql:
            locks.append(sql)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    res = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/cancel",
        headers=auth_headers(t.token),
    )
    monkeypatch.undo()

    assert res.status_code == 200, res.text
    assert len(locks) == 1, locks
    assert "appointments.id = " in locks[0], locks[0]
    assert "appointments.store_id = " in locks[0], locks[0]
