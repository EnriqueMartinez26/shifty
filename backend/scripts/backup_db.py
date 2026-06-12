from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def _normalize_postgres_url(raw_url: str) -> str:
    return (
        raw_url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )


def _build_pg_dump_command(
    database_url: str, backup_path: Path
) -> tuple[list[str], dict[str, str]]:
    parsed = urlparse(_normalize_postgres_url(database_url))
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise ValueError("DATABASE_URL no contiene nombre de base de datos")

    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--host",
        parsed.hostname or "localhost",
        "--port",
        str(parsed.port or 5432),
        "--username",
        parsed.username or "postgres",
        "--file",
        str(backup_path),
        database_name,
    ]

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
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
        default=os.environ.get("DATABASE_URL", ""),
        help="URL de base de datos. Si se omite, usa DATABASE_URL",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL requerido")

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
