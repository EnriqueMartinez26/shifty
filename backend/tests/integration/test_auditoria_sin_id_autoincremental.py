"""La auditoria no expone el autoincremental global de ``audit_logs``.

AUD2-B3-14, 2026-09-20. Sintoma: ``AuditLog.id`` es un entero autoincremental
GLOBAL (PK simple, sin ULID, por performance de insercion) y
``GET /superadmin/stores/{id}/audit-logs`` lo devolvia tal cual como
``public_id=str(log.id)``. Quien mira la auditoria de una tienda ve el
contador de acciones auditadas de TODA la plataforma y, restando dos
lecturas, estima el volumen y el crecimiento del resto de los tenants.
Hoy solo lo lee el superadmin; queda como canal lateral entre tiendas el dia
que el panel del dueno lea su propia auditoria.

Decision: el ``public_id`` pasa a ser un opaco derivado del entero con HMAC y
la clave del servidor (``modules/audit/public_id.py``): estable entre lecturas
(el front lo usa como ``key`` de React), distinto por fila, y sin relacion
visible con el contador. No hay migracion ni ULID en la tabla: la fila no se
busca por ese id desde ningun endpoint. El criterio queda escrito en el
modelo.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditLog
from tests.integration.test_auditoria_de_tienda_por_store_id import _superadmin

JsonDict = dict[str, Any]


async def _logs(
    client: AsyncClient, headers: dict[str, str], store_public_id: str
) -> list[JsonDict]:
    res = await client.get(
        f"/superadmin/stores/{store_public_id}/audit-logs?limit=15", headers=headers
    )
    assert res.status_code == 200, res.text
    return cast(list[JsonDict], res.json())


@pytest.mark.asyncio
async def test_el_public_id_de_la_auditoria_no_es_el_contador_global(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda_pid, headers = await _superadmin(client, test_session, "b314-audit")
    for nombre in ("Tienda Uno", "Tienda Dos"):
        editar = await client.patch(
            f"/superadmin/stores/{tienda_pid}", headers=headers, json={"name": nombre}
        )
        assert editar.status_code == 200, editar.text

    logs = await _logs(client, headers, tienda_pid)
    assert len(logs) == 2, logs
    ids_reales = {
        str(fila)
        for fila in (await test_session.execute(select(AuditLog.id))).scalars()
    }
    assert ids_reales, "las ediciones tenian que dejar filas de auditoria"

    publicos = [str(entrada["public_id"]) for entrada in logs]
    for publico in publicos:
        assert publico not in ids_reales, f"expone el entero de la fila: {publico}"
        assert not publico.isdigit(), f"sigue siendo un contador: {publico}"
    assert len(set(publicos)) == len(publicos), "dos filas con el mismo public_id"

    # Estable entre lecturas: el panel lo usa como clave de cada entrada.
    assert [str(e["public_id"]) for e in await _logs(client, headers, tienda_pid)] == (
        publicos
    )
