from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def _normalize_postgres_url(raw_url: str) -> str:
    return (
        raw_url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )


def _build_pg_restore_command(database_url: str, backup_path: Path) -> tuple[list[str], dict[str, str]]:
    parsed = urlparse(_normalize_postgres_url(database_url))
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise ValueError("DATABASE_URL no contiene nombre de base de datos")

    command = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host",
        parsed.hostname or "localhost",
        "--port",
        str(parsed.port or 5432),
        "--username",
        parsed.username or "postgres",
        "--dbname",
        database_name,
        str(backup_path),
    ]

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    return command, env


def main() -> int:
    parser = argparse.ArgumentParser(description="Restaura backup PostgreSQL en formato custom (pg_restore).")
    parser.add_argument("--backup-file", required=True, help="Ruta al archivo .dump")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="URL de base de datos destino. Si se omite, usa DATABASE_URL",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL requerido")

    backup_path = Path(args.backup_file)
    if not backup_path.exists():
        raise SystemExit(f"Backup no encontrado: {backup_path}")

    command, env = _build_pg_restore_command(args.database_url, backup_path)
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip())
        raise SystemExit(result.returncode)

    print(f"Restore completado desde: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
