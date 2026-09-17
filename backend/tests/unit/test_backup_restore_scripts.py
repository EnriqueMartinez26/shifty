from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str) -> ModuleType:
    script_path = BACKEND_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_command_uses_pg_dump_without_exposing_password(tmp_path: Path) -> None:
    backup_db = load_script("backup_db")

    command, env = backup_db._build_pg_dump_command(
        "postgresql+asyncpg://app_user:secret@db.example.com:6543/shifty_prod",
        tmp_path / "shifty.dump",
    )

    assert command[:3] == ["pg_dump", "--format=custom", "--no-owner"]
    assert "--no-privileges" in command
    assert command[command.index("--host") + 1] == "db.example.com"
    assert command[command.index("--port") + 1] == "6543"
    assert command[command.index("--username") + 1] == "app_user"
    assert command[-1] == "shifty_prod"
    assert "secret" not in command
    assert env["PGPASSWORD"] == "secret"


def test_restore_command_uses_pg_restore_without_exposing_password(
    tmp_path: Path,
) -> None:
    restore_backup = load_script("restore_backup")
    backup_file = tmp_path / "shifty.dump"

    command, env = restore_backup._build_pg_restore_command(
        "postgres://restore_user:restore_secret@localhost/shifty_drill",
        backup_file,
    )

    assert command[:3] == ["pg_restore", "--clean", "--if-exists"]
    # 2026-09-17 · C-06: sin --exit-on-error pg_restore devuelve 0 aunque
    # fallen objetos; un dump truncado "restauraba" con evidencia ok.
    assert "--exit-on-error" in command
    assert "--no-owner" in command
    assert "--no-privileges" in command
    assert command[command.index("--host") + 1] == "localhost"
    assert command[command.index("--port") + 1] == "5432"
    assert command[command.index("--username") + 1] == "restore_user"
    assert command[command.index("--dbname") + 1] == "shifty_drill"
    assert command[-1] == str(backup_file)
    assert "restore_secret" not in command
    assert env["PGPASSWORD"] == "restore_secret"


def test_backup_restore_drill_writes_success_evidence_for_existing_backup(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    drill = load_script("backup_restore_drill")
    backup_dir = tmp_path / "backups"
    evidence_dir = tmp_path / "evidence"
    backup_dir.mkdir()
    backup_file = backup_dir / "shifty-20260621T120000Z.dump"
    checksum_file = backup_dir / "shifty-20260621T120000Z.sha256"
    backup_file.write_bytes(b"fake custom dump")
    # 2026-09-17 · C-06: el checksum tiene que ser el real del dump; antes el
    # drill lo registraba sin recalcularlo y "abc123" daba evidencia ok.
    digest = hashlib.sha256(b"fake custom dump").hexdigest()
    checksum_file.write_text(f"{digest}  {backup_file.name}\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(backup_dir),
            "--evidence-dir",
            str(evidence_dir),
        ],
    )

    assert drill.main() == 0
    evidence_files = list(evidence_dir.glob("drill-*.json"))
    assert len(evidence_files) == 1
    evidence = json.loads(evidence_files[0].read_text(encoding="utf-8"))
    assert evidence["status"] == "ok"
    assert evidence["backup_file"] == str(backup_file)
    assert evidence["checksum_file"] == str(checksum_file)
    assert "duration_seconds" in evidence
    verify = next(
        step for step in evidence["steps"] if step["name"] == "verify-checksum"
    )
    assert verify["ok"] is True


def test_backup_restore_drill_fails_when_checksum_does_not_match(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """2026-09-17 · C-06: el drill guardaba la ruta del `.sha256` como evidencia
    pero nunca lo recalculaba ni comparaba. Sintoma: un dump truncado (o un
    checksum de otro archivo) producia `"status": "ok"` y el runbook que gatea
    releases quedaba verde sin haber validado nada."""
    drill = load_script("backup_restore_drill")
    backup_dir = tmp_path / "backups"
    evidence_dir = tmp_path / "evidence"
    backup_dir.mkdir()
    backup_file = backup_dir / "shifty-20260621T120000Z.dump"
    checksum_file = backup_dir / "shifty-20260621T120000Z.sha256"
    backup_file.write_bytes(b"dump truncado a mitad de cami")
    digest_completo = hashlib.sha256(b"dump completo").hexdigest()
    checksum_file.write_text(
        f"{digest_completo}  {backup_file.name}\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(backup_dir),
            "--evidence-dir",
            str(evidence_dir),
        ],
    )

    assert drill.main() == 1
    evidence = json.loads(
        next(evidence_dir.glob("drill-*.json")).read_text(encoding="utf-8")
    )
    assert evidence["status"] == "failed"
    verify = next(
        step for step in evidence["steps"] if step["name"] == "verify-checksum"
    )
    assert verify["ok"] is False
    assert digest_completo in verify["stderr"]


def test_backup_restore_drill_fails_when_checksum_file_is_missing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """2026-09-17 · C-06: un dump sin su `.sha256` no se puede validar; antes el
    drill lo daba por bueno en silencio."""
    drill = load_script("backup_restore_drill")
    backup_dir = tmp_path / "backups"
    evidence_dir = tmp_path / "evidence"
    backup_dir.mkdir()
    (backup_dir / "shifty-20260621T120000Z.dump").write_bytes(b"fake custom dump")

    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(backup_dir),
            "--evidence-dir",
            str(evidence_dir),
        ],
    )

    assert drill.main() == 1
    evidence = json.loads(
        next(evidence_dir.glob("drill-*.json")).read_text(encoding="utf-8")
    )
    assert evidence["status"] == "failed"
    assert "checksum_file" not in evidence
    verify = next(
        step for step in evidence["steps"] if step["name"] == "verify-checksum"
    )
    assert verify["ok"] is False


def test_backup_restore_drill_records_failed_backup_without_database(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    drill = load_script("backup_restore_drill")
    evidence_dir = tmp_path / "evidence"

    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(tmp_path / "backups"),
            "--evidence-dir",
            str(evidence_dir),
            "--run-backup",
        ],
    )

    assert drill.main() == 1
    evidence_file = next(evidence_dir.glob("drill-*.json"))
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert any(
        step["name"] == "backup" and "DATABASE_URL" in step["stderr"]
        for step in evidence["steps"]
    )
    assert any(step["name"] == "locate-backup" for step in evidence["steps"])
