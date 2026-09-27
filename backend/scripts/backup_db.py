"""Backup logico de la base con pg_dump (formato custom + sha256).

Corre con el rol DUENO de la base, nunca con el de la app (F0-20,
2026-09-24): `DATABASE_URL` es `shifty_app`, sin BYPASSRLS, y bajo RLS
`pg_dump` aborta o vuelca solo lo que la politica deja ver. La URL sale de
`--database-url`, `BACKUP_DATABASE_URL` o `MIGRATION_DATABASE_URL`, en ese
orden; una URL del rol de la app se rechaza aunque venga explicita.

El backup diario de produccion NO usa este script: lo hace `scripts/backup.sh`
en el host, con `pg_dump` dentro del contenedor de la base. Este queda para el
drill mensual y para un backup manual contra una base alcanzable por red.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

# Se invoca como `python scripts/backup_db.py`: sys.path[0] es scripts/, no la
# raiz del backend, y core.config vive ahi.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.config import parse_db_url, redact_url  # noqa: E402

# Variables que pueden traer la URL del dueno, en orden de preferencia.
# DATABASE_URL NO esta: es el rol de la app, con RLS.
OWNER_URL_VARIABLES = ("BACKUP_DATABASE_URL", "MIGRATION_DATABASE_URL")
DEFAULT_APP_DB_USER = "shifty_app"


def _default_database_url(environ: Mapping[str, str]) -> str:
    for variable in OWNER_URL_VARIABLES:
        valor = environ.get(variable, "").strip()
        if valor:
            return valor
    return ""


def _es_rol_de_la_app(database_url: str, environ: Mapping[str, str]) -> bool:
    """Si la URL es la del rol con RLS: la misma que DATABASE_URL o su usuario."""
    app_url = environ.get("DATABASE_URL", "").strip()
    if app_url and app_url == database_url.strip():
        return True
    usuario = parse_db_url(database_url, label="BACKUP_DATABASE_URL")["user"]
    return bool(usuario) and usuario == environ.get("APP_DB_USER", DEFAULT_APP_DB_USER)


def _build_pg_dump_command(
    database_url: str, backup_path: Path
) -> tuple[list[str], dict[str, str]]:
    # Misma lectura que las migraciones (core.config.parse_db_url, regla 17):
    # `ssl` de asyncpg o `sslmode`, `require` si la URL no dice nada, y la
    # contrasena decodificada (`%40` es `@`).
    partes = parse_db_url(database_url, label="BACKUP_DATABASE_URL")

    # Sin --no-privileges (drill 2026-09-24): el dump tiene que traer los GRANT
    # y los ALTER DEFAULT PRIVILEGES de shifty_app; sin ellos la base
    # restaurada le niega todo a la app.
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--host",
        str(partes["host"]),
        "--port",
        str(partes["port"]),
        "--username",
        str(partes["user"] or "postgres"),
        "--file",
        str(backup_path),
        str(partes["dbname"]),
    ]

    env = os.environ.copy()
    env["PGSSLMODE"] = str(partes["sslmode"])
    if partes["password"]:
        env["PGPASSWORD"] = str(partes["password"])
    return command, env


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera backup PostgreSQL en formato custom (pg_dump)."
    )
    parser.add_argument(
        "--output-dir",
        default="backups",
        help="Directorio de salida para los backups (default: backups)",
    )
    parser.add_argument(
        "--database-url",
        default=_default_database_url(os.environ),
        help=(
            "URL del rol DUENO de la base. Si se omite, usa BACKUP_DATABASE_URL "
            "o MIGRATION_DATABASE_URL (nunca DATABASE_URL: es el rol con RLS)"
        ),
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit(
            "Falta la URL del dueno de la base: BACKUP_DATABASE_URL o "
            "MIGRATION_DATABASE_URL (DATABASE_URL es el rol de la app, con RLS, "
            "y no sirve para pg_dump)"
        )
    if _es_rol_de_la_app(args.database_url, os.environ):
        raise SystemExit(
            "La URL de backup es la del rol de la app, sujeto a RLS: pg_dump "
            "abortaria o volcaria solo lo que la politica deja ver. Usar el rol "
            f"dueno ({redact_url(args.database_url, keep_target=True)})"
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = output_dir / f"shifty-{timestamp}.dump"
    checksum_path = output_dir / f"shifty-{timestamp}.sha256"

    command, env = _build_pg_dump_command(args.database_url, backup_path)
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(result.stderr.strip())
        raise SystemExit(result.returncode)

    checksum = _sha256_file(backup_path)
    checksum_path.write_text(f"{checksum}  {backup_path.name}\n", encoding="utf-8")

    print(f"Backup generado: {backup_path}")
    print(f"Checksum: {checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
