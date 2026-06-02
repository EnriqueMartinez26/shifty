from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _run(command: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _latest_backup(backup_dir: Path) -> Path | None:
    backups = sorted(backup_dir.glob("shifty-*.dump"), reverse=True)
    return backups[0] if backups else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecuta drill de backup+restore y guarda evidencia JSON.")
    parser.add_argument("--backup-dir", default="backups", help="Directorio de backups")
    parser.add_argument("--evidence-dir", default="backups/evidence", help="Directorio de evidencias")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument(
        "--restore-database-url",
        default=os.environ.get("DRILL_DATABASE_URL", ""),
        help="Base de destino para el restore drill (staging temporal)",
    )
    parser.add_argument(
        "--run-backup",
        action="store_true",
        help="Genera un nuevo backup antes del drill",
    )
    parser.add_argument(
        "--run-restore",
        action="store_true",
        help="Ejecuta restore en restore-database-url",
    )
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc)
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    evidence: dict[str, object] = {
        "started_at": started_at.isoformat(),
        "status": "ok",
        "steps": [],
    }

    def add_step(name: str, ok: bool, stdout: str = "", stderr: str = "") -> None:
        evidence["steps"].append(
            {
                "name": name,
                "ok": ok,
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
            }
        )
        if not ok:
            evidence["status"] = "failed"

    if args.run_backup:
        if not args.database_url:
            add_step("backup", False, stderr="DATABASE_URL no configurado")
        else:
            code, out, err = _run(
                ["python", "scripts/backup_db.py", "--output-dir", str(backup_dir), "--database-url", args.database_url]
            )
            add_step("backup", code == 0, out, err)

    latest = _latest_backup(backup_dir)
    if latest:
        evidence["backup_file"] = str(latest)
        checksum_file = latest.with_suffix(".sha256")
        if checksum_file.exists():
            evidence["checksum_file"] = str(checksum_file)
    else:
        add_step("locate-backup", False, stderr="No se encontro backup para validar")

    if args.run_restore:
        if not latest:
            add_step("restore", False, stderr="No hay backup para restore")
        elif not args.restore_database_url:
            add_step("restore", False, stderr="DRILL_DATABASE_URL no configurado")
        else:
            code, out, err = _run(
                [
                    "python",
                    "scripts/restore_backup.py",
                    "--backup-file",
                    str(latest),
                    "--database-url",
                    args.restore_database_url,
                ]
            )
            add_step("restore", code == 0, out, err)

    finished_at = datetime.now(timezone.utc)
    evidence["finished_at"] = finished_at.isoformat()
    evidence["duration_seconds"] = int((finished_at - started_at).total_seconds())

    evidence_path = evidence_dir / f"drill-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"Evidencia generada: {evidence_path}")
    return 0 if evidence.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
