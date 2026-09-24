"""Top de consultas de ``pg_stat_statements`` (F5-03, R7-04, R11-14).

Imprime las consultas que mas tiempo total y mas tiempo medio consumen en la
base de la app, con llamadas, filas y su peso sobre el total. Lo corre un cron
semanal en el host (``deploy/cron/shifty-pg-top``) dentro del contenedor del
backend; la salida queda en ``/var/log/shifty/pg-top.log``.

Conecta con el rol DUENO (``--database-url``, ``BACKUP_DATABASE_URL`` o
``MIGRATION_DATABASE_URL``, en ese orden), nunca con ``DATABASE_URL``: la
vista necesita ``pg_read_all_stats`` o superusuario, y ``shifty_app`` solo
veria sus propias sentencias con el texto tapado. La URL no se imprime con
credenciales. El texto de las consultas viene normalizado por Postgres
(``$1`` en vez de valores), asi que no trae datos de clientes.

``--reset`` vacia las estadisticas DESPUES de imprimirlas, para que el
reporte siguiente mida solo esa semana.

    python scripts/pg_top_queries.py [--limit 20] [--reset]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_ROOT / "scripts"
for _ruta in (BACKEND_ROOT, SCRIPTS_DIR):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

from backup_db import (  # noqa: E402
    OWNER_URL_VARIABLES,
    _default_database_url,
    _es_rol_de_la_app,
)
from core.config import parse_db_url, redact_url  # noqa: E402

DEFAULT_LIMIT = 20
QUERY_WIDTH = 180

_ORDENES = ("total_exec_time", "mean_exec_time")

_SQL_TOTALES = """
SELECT coalesce(sum(s.total_exec_time), 0), coalesce(sum(s.calls), 0)
FROM pg_stat_statements s
JOIN pg_database d ON d.oid = s.dbid
WHERE d.datname = current_database()
"""

_SQL_TOP = """
SELECT s.queryid, s.calls, s.total_exec_time, s.mean_exec_time, s.rows, s.query
FROM pg_stat_statements s
JOIN pg_database d ON d.oid = s.dbid
WHERE d.datname = current_database()
ORDER BY s.{columna} DESC
LIMIT %s
"""


class ErrorDeBase(Exception):
    """Error al consultar la vista (extension ausente, permisos)."""


class Cursor(Protocol):
    def execute(self, sql: str, params: Any = ...) -> Any: ...

    def fetchall(self) -> Sequence[Sequence[Any]]: ...

    def fetchone(self) -> Sequence[Any] | None: ...


@dataclass(frozen=True)
class Consulta:
    queryid: int
    calls: int
    total_ms: float
    mean_ms: float
    rows: int
    query: str


@dataclass(frozen=True)
class Reporte:
    total_ms: float
    total_calls: int
    por_orden: dict[str, list[Consulta]]


def _owner_url(environ: Mapping[str, str]) -> str:
    return str(_default_database_url(environ))


def _origen(environ: Mapping[str, str]) -> str:
    """Variable de la que salio la URL por defecto, para nombrarla en errores."""
    for variable in OWNER_URL_VARIABLES:
        if environ.get(variable, "").strip():
            return str(variable)
    return "MIGRATION_DATABASE_URL"


def recolectar(cursor: Cursor, *, limite: int) -> Reporte:
    cursor.execute(_SQL_TOTALES)
    fila = cursor.fetchone() or (0, 0)
    por_orden: dict[str, list[Consulta]] = {}
    for columna in _ORDENES:
        cursor.execute(_SQL_TOP.format(columna=columna), (limite,))
        por_orden[columna] = [
            Consulta(
                queryid=int(r[0] or 0),
                calls=int(r[1] or 0),
                total_ms=float(r[2] or 0),
                mean_ms=float(r[3] or 0),
                rows=int(r[4] or 0),
                query=str(r[5] or ""),
            )
            for r in cursor.fetchall()
        ]
    return Reporte(
        total_ms=float(fila[0] or 0),
        total_calls=int(fila[1] or 0),
        por_orden=por_orden,
    )


def reiniciar(cursor: Cursor) -> None:
    cursor.execute("SELECT pg_stat_statements_reset()")


def _una_linea(query: str) -> str:
    plano = " ".join(query.split())
    if len(plano) <= QUERY_WIDTH:
        return plano
    return plano[: QUERY_WIDTH - 3] + "..."


def formatear(reporte: Reporte, *, destino: str) -> str:
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lineas = [
        f"pg_stat_statements {ahora} base={destino}",
        f"total: {reporte.total_ms:.0f} ms en {reporte.total_calls} llamadas",
    ]
    for columna, consultas in reporte.por_orden.items():
        lineas.append("")
        lineas.append(f"== top {len(consultas)} por {columna} ==")
        lineas.append(
            f"{'total_ms':>12} {'mean_ms':>10} {'calls':>10} {'rows':>10} "
            f"{'%total':>7}  consulta"
        )
        for c in consultas:
            peso = 100 * c.total_ms / reporte.total_ms if reporte.total_ms else 0.0
            lineas.append(
                f"{c.total_ms:>12.1f} {c.mean_ms:>10.2f} {c.calls:>10} "
                f"{c.rows:>10} {peso:>6.1f}%  {_una_linea(c.query)}"
            )
    return "\n".join(lineas) + "\n"


def _connect(database_url: str, *, label: str) -> Any:
    import psycopg2

    partes = parse_db_url(database_url, label=label)
    return psycopg2.connect(**partes, connect_timeout=10)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Top de consultas por tiempo total y medio (pg_stat_statements)."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "URL del rol DUENO. Si se omite, BACKUP_DATABASE_URL o "
            "MIGRATION_DATABASE_URL (nunca DATABASE_URL: es el rol con RLS)"
        ),
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Vacia las estadisticas despues de imprimirlas",
    )
    args = parser.parse_args(argv)
    if args.database_url is None:
        args.database_url = _owner_url(os.environ)
        origen = _origen(os.environ)
    else:
        origen = "--database-url"

    if not args.database_url:
        raise SystemExit(
            "Falta la URL del dueno de la base: BACKUP_DATABASE_URL o "
            "MIGRATION_DATABASE_URL (DATABASE_URL es el rol de la app, con RLS)"
        )
    destino = redact_url(args.database_url, keep_target=True)
    try:
        es_de_la_app = _es_rol_de_la_app(args.database_url, os.environ)
    except ValueError as exc:
        raise SystemExit(f"{origen}: {exc}") from None
    if es_de_la_app:
        raise SystemExit(
            "La URL es la del rol de la app, sujeto a RLS: pg_stat_statements "
            f"le esconde el texto de las consultas ajenas. Usar el rol dueno "
            f"({destino})"
        )
    limite = max(1, min(int(args.limit), 200))

    try:
        conexion = _connect(args.database_url, label=origen)
    except Exception as exc:
        raise SystemExit(
            f"No se pudo conectar a {destino} (URL de {origen}): "
            f"{type(exc).__name__}: {redact_url(str(exc), keep_target=True)}"
        ) from None
    try:
        conexion.autocommit = True
        cursor = conexion.cursor()
        try:
            reporte = recolectar(cursor, limite=limite)
            sys.stdout.write(formatear(reporte, destino=destino))
            if args.reset:
                reiniciar(cursor)
                sys.stdout.write("estadisticas reiniciadas\n")
        except Exception as exc:
            raise SystemExit(
                f"No se pudo leer pg_stat_statements en {destino}: "
                f"{type(exc).__name__}: {redact_url(str(exc), keep_target=True)} "
                "(la extension se precarga en compose y la crea la migracion "
                "b2c4e6a8d0f3; el rol necesita pg_read_all_stats)"
            ) from None
    finally:
        conexion.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
