"""Restore de un dump en formato custom (pg_restore) sobre una base destino.

Drill 2026-09-24: los roles son objetos del CLUSTER y no viajan en el dump de
una base. El dump trae `GRANT ... TO shifty_app` y `ALTER DEFAULT PRIVILEGES`,
asi que el rol de la app tiene que existir en el destino ANTES de pg_restore:
sin el, `--exit-on-error` aborta en `GRANT USAGE ON SCHEMA public TO
shifty_app` y deja la base a medias. Este script lo comprueba y se niega a
restaurar si falta; con `--create-app-role` lo crea (NOSUPERUSER, NOBYPASSRLS
y los timeouts de la migracion c2e4f6a8b0d1, que tampoco estan en el dump).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_APP_DB_USER = "shifty_app"
# Identificador simple de Postgres, sin comillas: el nombre del rol se escribe
# en el SQL (el DDL no acepta parametros ligados) y no puede traer nada mas.
_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]{0,62}")
# Timeouts del rol de la app (migracion c2e4f6a8b0d1_app_role_timeouts). Son
# `ALTER ROLE ... SET`, del cluster: pg_dump no los guarda.
TIMEOUTS_DEL_ROL_APP = (
    ("statement_timeout", "30s"),
    ("lock_timeout", "5s"),
    ("idle_in_transaction_session_timeout", "60s"),
)


def _normalize_postgres_url(raw_url: str) -> str:
    return (
        raw_url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )


def _conexion(database_url: str) -> tuple[list[str], dict[str, str]]:
    """Argumentos de conexion comunes a pg_restore y psql, y el entorno con la
    contrasena (nunca en argv). Un solo parseo de la URL para los dos
    (AUD2-C-04, 2026-09-19)."""
    parsed = urlparse(_normalize_postgres_url(database_url))
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise ValueError("DATABASE_URL no contiene nombre de base de datos")

    argumentos = [
        "--host",
        parsed.hostname or "localhost",
        "--port",
        str(parsed.port or 5432),
        "--username",
        parsed.username or "postgres",
        "--dbname",
        database_name,
    ]
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    return argumentos, env


def _build_pg_restore_command(
    database_url: str, backup_path: Path
) -> tuple[list[str], dict[str, str]]:
    conexion, env = _conexion(database_url)
    command = [
        "pg_restore",
        "--clean",
        "--if-exists",
        # Sin esto pg_restore devuelve 0 aunque fallen objetos y el drill
        # daba por buena una restauracion parcial (C-06, 2026-09-17).
        "--exit-on-error",
        "--no-owner",
        # Sin --no-privileges (drill 2026-09-24): descartaba los GRANT y los
        # default ACL de shifty_app y la app recibia "permission denied".
        *conexion,
        str(backup_path),
    ]
    return command, env


def _build_psql_command(
    database_url: str, sql: str | None
) -> tuple[list[str], dict[str, str]]:
    """psql contra la base destino, en formato plano.

    Con `sql` es una consulta de UNA fila por `--command`. Con `None` el SQL va
    por stdin, en una sola transaccion: es el camino del DDL que lleva la
    contrasena del rol, que no puede quedar en argv (visible en `ps`).
    """
    conexion, env = _conexion(database_url)
    command = [
        "psql",
        # -A sin alinear, -t sin encabezado, -X ignora el .psqlrc del runner,
        # ON_ERROR_STOP para que una tabla faltante sea exit code != 0.
        "-AtX",
        "--variable",
        "ON_ERROR_STOP=1",
        *conexion,
    ]
    if sql is None:
        command.append("--single-transaction")
    else:
        command += ["--command", sql]
    return command, env


def _rol_de_la_app(environ: Mapping[str, str]) -> str:
    rol = environ.get("APP_DB_USER", "").strip() or DEFAULT_APP_DB_USER
    if not _IDENTIFICADOR.fullmatch(rol):
        raise ValueError(
            "APP_DB_USER no es un identificador simple de Postgres (minusculas, "
            "digitos y guion bajo): no se puede usar como nombre del rol de la app"
        )
    return rol


def _literal_sql(valor: str) -> str:
    """Literal SQL con la semantica de quote_literal (igual que la migracion
    c3d4e5f6a7b8): comilla simple duplicada y, con barras invertidas, E''."""
    escapado = valor.replace("'", "''")
    if "\\" in valor:
        return "E'" + escapado.replace("\\", "\\\\") + "'"
    return "'" + escapado + "'"


def _sql_rol_de_la_app(rol: str, clave: str | None) -> str:
    """Crea el rol (si viene `clave`) y fija lo que el dump no trae: sin
    superusuario ni BYPASSRLS, y los timeouts de c2e4f6a8b0d1."""
    ident = f'"{rol}"'
    sentencias: list[str] = []
    if clave is not None:
        sentencias.append(
            f"CREATE ROLE {ident} LOGIN PASSWORD {_literal_sql(clave)} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;"
        )
    sentencias.append(f"ALTER ROLE {ident} NOSUPERUSER NOBYPASSRLS;")
    for parametro, valor in TIMEOUTS_DEL_ROL_APP:
        sentencias.append(f"ALTER ROLE {ident} SET {parametro} = '{valor}';")
    return "\n".join(sentencias) + "\n"


def _ocultar(texto: str, clave: str | None) -> str:
    """psql repite la linea que fallo (LINE 1: ...): la clave no sale nunca."""
    if not clave:
        return texto
    for forma in (
        _literal_sql(clave),
        clave.replace("'", "''").replace("\\", "\\\\"),
        clave.replace("'", "''"),
        clave,
    ):
        texto = texto.replace(forma, "***")
    return texto


def _existe_rol(database_url: str, rol: str) -> bool:
    command, env = _build_psql_command(
        database_url, f"select 1 from pg_roles where rolname = '{rol}'"
    )
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            f"No se pudo consultar pg_roles en el destino: {result.stderr.strip()}"
        )
    return result.stdout.strip() == "1"


def _clave_del_rol_app(environ: Mapping[str, str], rol: str) -> str:
    clave = environ.get("APP_DB_PASSWORD", "").strip()
    if not clave:
        raise SystemExit(
            f"--create-app-role necesita APP_DB_PASSWORD: es la contrasena con "
            f"la que se crea {rol} (la misma que usa la app en DATABASE_URL)."
        )
    if any(ord(c) < 32 or ord(c) == 127 for c in clave):
        raise SystemExit(
            "APP_DB_PASSWORD contiene caracteres de control: no se puede usar "
            f"como contrasena de {rol}."
        )
    return clave


def _asegurar_rol_de_la_app(database_url: str, rol: str, *, crear: bool) -> None:
    existe = _existe_rol(database_url, rol)
    if not existe and not crear:
        raise SystemExit(
            f"El rol {rol} no existe en la base destino. Los roles son del "
            "cluster y no viajan en el dump: pg_restore --exit-on-error "
            f"abortaria en `GRANT USAGE ON SCHEMA public TO {rol}` y dejaria la "
            "base a medias. Crealo antes (docs/BACKUP_RESTORE_RUNBOOK.md) o "
            "volve a correr con --create-app-role y APP_DB_PASSWORD."
        )
    if not crear:
        return

    clave = None if existe else _clave_del_rol_app(os.environ, rol)
    command, env = _build_psql_command(database_url, None)
    result = subprocess.run(
        command,
        input=_sql_rol_de_la_app(rol, clave),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"No se pudo preparar el rol {rol}: "
            f"{_ocultar(result.stderr.strip(), clave)}"
        )
    accion = "ajustado" if existe else "creado"
    print(f"Rol {rol} {accion}: NOSUPERUSER NOBYPASSRLS y timeouts de c2e4f6a8b0d1")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restaura backup PostgreSQL en formato custom (pg_restore)."
    )
    parser.add_argument("--backup-file", required=True, help="Ruta al archivo .dump")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="URL de base de datos destino. Si se omite, usa DATABASE_URL",
    )
    parser.add_argument(
        "--create-app-role",
        action="store_true",
        help=(
            "Si el rol de la app (APP_DB_USER, default shifty_app) no existe en "
            "el destino, lo crea con la contrasena de APP_DB_PASSWORD; en los "
            "dos casos le fija NOSUPERUSER NOBYPASSRLS y los timeouts"
        ),
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL requerido")

    backup_path = Path(args.backup_file)
    if not backup_path.exists():
        raise SystemExit(f"Backup no encontrado: {backup_path}")

    try:
        rol = _rol_de_la_app(os.environ)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    _asegurar_rol_de_la_app(args.database_url, rol, crear=args.create_app_role)

    command, env = _build_pg_restore_command(args.database_url, backup_path)
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(result.stderr.strip())
        raise SystemExit(result.returncode)

    print(f"Restore completado desde: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
