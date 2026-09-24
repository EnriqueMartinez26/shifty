"""EXPLAIN de las consultas REALES de la app, como ``shifty_app`` y bajo RLS.

Plan de rendimiento, R7 (2026-09-24): bajo RLS solo los predicados leakproof
pueden ser ``Index Cond`` (``texteq``, comparaciones de ``timestamptz``,
``= ANY``); ``lower()``, ``&&`` o ``timezone()`` quedan como filtro y la
consulta recorre la tabla o el indice entero. Por eso estas pruebas no
reescriben la consulta a mano: capturan la sentencia que la app manda
(``before_cursor_execute``) y la explican con los mismos parametros.

La base de pruebas es chica: con ``enable_seqscan = off`` el plan no dice cuan
rapido es, dice QUE indice puede usar la consulta y con que condiciones. Eso
es lo que se fija.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

Sentencia = tuple[str, Any]


@contextmanager
def sentencias_capturadas(engine: AsyncEngine) -> Iterator[list[Sentencia]]:
    """Lista de (sql, parametros) que el engine manda mientras dura el bloque."""
    capturadas: list[Sentencia] = []

    def registrar(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        capturadas.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        yield capturadas
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)


async def plan_de(
    engine: AsyncEngine,
    sentencia: Sentencia,
    *,
    store_id: str = "",
    global_admin: bool = False,
) -> dict[str, Any]:
    """Plan (FORMAT JSON) de la sentencia, con el contexto de tienda de la app."""
    sql, parametros = sentencia
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "SELECT set_config('app.current_store_id', :sid, true), "
                    "set_config('app.is_global_admin', :admin, true)"
                ),
                {"sid": store_id, "admin": "true" if global_admin else "false"},
            )
            await conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
            crudo = (
                await conn.exec_driver_sql(
                    "EXPLAIN (FORMAT JSON) " + sql, parametros or ()
                )
            ).scalar_one()
    documento = json.loads(crudo) if isinstance(crudo, str) else crudo
    plan: dict[str, Any] = documento[0]["Plan"]
    return plan


def nodos(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield plan
    for hijo in plan.get("Plans", []):
        yield from nodos(hijo)


def condiciones_de_indice(plan: dict[str, Any]) -> dict[str, str]:
    """Indice usado -> su ``Index Cond`` (vacio si el nodo no tiene)."""
    return {
        str(nodo["Index Name"]): str(nodo.get("Index Cond", ""))
        for nodo in nodos(plan)
        if "Index Name" in nodo
    }


def escaneos_secuenciales(plan: dict[str, Any]) -> list[str]:
    return [
        str(nodo.get("Relation Name"))
        for nodo in nodos(plan)
        if nodo.get("Node Type") == "Seq Scan"
    ]


def resumen(plan: dict[str, Any]) -> str:
    """Una linea por nodo, para el mensaje de un assert que falla."""
    return "\n".join(
        f"{nodo.get('Node Type')} {nodo.get('Relation Name', '')} "
        f"{nodo.get('Index Name', '')} cond={nodo.get('Index Cond', '')} "
        f"filter={nodo.get('Filter', '')}"
        for nodo in nodos(plan)
    )
