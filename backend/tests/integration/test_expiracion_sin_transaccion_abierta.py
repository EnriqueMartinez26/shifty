"""``expire_unpaid_appointments`` cierra la transaccion antes de salir a MP.

2026-09-18, seguimiento S-02 de la revision de B2-02: B2-02 saco la llamada a
Mercado Pago de debajo del ``FOR UPDATE``, pero la fase A (lectura del lote)
dejaba la transaccion ABIERTA durante todo el HTTP (hasta 20 s por cobro).
Ademas cada consulta a MP releia ``payment_gateway_configs`` entre request y
request, asi que la sesion quedaba ``idle in transaction`` durante la fase
entera. Con ``idle_in_transaction_session_timeout = 60s`` en el rol de la app
(migracion ``app_role_timeouts``) y MP degradado, Postgres mata la conexion
a mitad del job y la fase B revienta (regla 5).

En SQLite se observa el ORDEN con eventos del engine: antes de la primera
llamada a MP hay un commit, y entre ese commit y la ultima llamada a MP no se
ejecuta ninguna sentencia SQL (ninguna transaccion reabierta durante el HTTP).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
from modules.payments.jobs import expire_unpaid_appointments
from tests.integration.test_expiracion_mp_fuera_del_lock import (
    _mercadopago_que_registra,
    _turno_vencido_con_sena_pendiente,
)
from tests.integration.test_mails_al_cliente import Buzon


def _sql_entre_el_commit_y_el_ultimo_http(linea: list[str]) -> list[str]:
    primero = linea.index("http")
    ultimo = len(linea) - 1 - linea[::-1].index("http")
    commits_previos = [i for i, e in enumerate(linea[:primero]) if e == "commit"]
    assert commits_previos, (
        f"se salio a Mercado Pago sin cerrar la transaccion: {linea}"
    )
    desde = commits_previos[-1]
    return [e for e in linea[desde:ultimo] if e == "sql"]


@pytest.mark.asyncio
async def test_la_fase_de_mercado_pago_corre_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea, remoto=None)
    await _turno_vencido_con_sena_pendiente(client, test_session, slug="s02", hour=10)
    linea.clear()

    def sql(*args: Any, **kwargs: Any) -> None:
        linea.append("sql")

    def commit(*args: Any, **kwargs: Any) -> None:
        linea.append("commit")

    event.listen(test_engine.sync_engine, "before_cursor_execute", sql)
    event.listen(test_engine.sync_engine, "commit", commit)
    try:
        stats = await expire_unpaid_appointments(test_session)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", sql)
        event.remove(test_engine.sync_engine, "commit", commit)

    assert stats["expired"] == 1, stats
    assert "http" in linea, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"la transaccion se reabrio durante las llamadas a Mercado Pago: {linea}"
    )
