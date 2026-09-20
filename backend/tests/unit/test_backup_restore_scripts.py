from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
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


def test_el_drill_lanza_sus_subprocesos_con_el_interprete_y_rutas_absolutas(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Defecto real (2026-09-17, C-17): `_run` usaba "python" y rutas relativas.

    Sintoma: `_run` no fijaba `cwd` ni usaba `sys.executable`; funcionaba solo
    porque el workflow mensual pone `working-directory: backend` y `uv run`
    deja el venv en el PATH. Desde la raiz del repo,
    `uv run python backend/scripts/backup_restore_drill.py --run-backup` moria
    con "can't open file 'scripts/backup_db.py'". El runbook de backup gatea
    releases (CLAUDE.md §6).
    """
    drill = load_script("backup_restore_drill")
    lanzados: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        lanzados.append({"command": list(command), "cwd": kwargs.get("cwd")})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drill.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(tmp_path / "backups"),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-backup",
            "--database-url",
            "postgresql://u:p@localhost:5432/d",
        ],
    )

    drill.main()

    assert lanzados, "el drill no lanzo ningun subproceso"
    lanzamiento = lanzados[0]
    command = lanzamiento["command"]
    assert isinstance(command, list)
    assert command[0] == sys.executable, (
        f"el drill invoca {command[0]!r} en vez del interprete que lo corre"
    )
    assert Path(command[1]).is_absolute(), (
        f"el drill pasa una ruta relativa al cwd: {command[1]!r}"
    )
    assert Path(command[1]).exists(), f"la ruta no existe: {command[1]!r}"
    assert lanzamiento["cwd"] == BACKEND_ROOT, (
        f"el drill no fija cwd en la raiz del backend: {lanzamiento['cwd']!r}"
    )
    # Con cwd fijo, un --output-dir relativo al cwd del drill caeria en otro
    # directorio que el que despues revisa _latest_backup.
    salida = command[command.index("--output-dir") + 1]
    assert Path(salida).is_absolute(), f"--output-dir relativo: {salida!r}"


# Lo que devuelve psql cuando el restore trajo una base con esquema y datos:
# version de alembic y los conteos de las tablas criticas.
VERIFICACION_OK = "d2f4a6b8c0e2|3|12|5"


def _drill_con_subprocess_falso(
    monkeypatch: MonkeyPatch,
    verificacion: tuple[int, str, str] = (0, VERIFICACION_OK, ""),
) -> tuple[ModuleType, list[list[str]]]:
    drill = load_script("backup_restore_drill")
    lanzados: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        lanzados.append(list(command))
        if command and command[0] == "psql":
            code, out, err = verificacion
            return SimpleNamespace(returncode=code, stdout=out, stderr=err)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drill.subprocess, "run", fake_run)
    return drill, lanzados


def _backup_en(directorio: Path) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    dump = directorio / "shifty-20260621T120000Z.dump"
    dump.write_bytes(b"fake custom dump")
    (directorio / "shifty-20260621T120000Z.sha256").write_text(
        f"{hashlib.sha256(b'fake custom dump').hexdigest()}  {dump.name}\n",
        encoding="utf-8",
    )
    return dump


@pytest.mark.parametrize(
    ("origen", "destino"),
    [
        (
            "postgresql://u:p@prod.example.com:5432/shifty",
            "postgresql://u:p@prod.example.com:5432/shifty",
        ),
        # Mismo destino real, escrito distinto: driver, credenciales y puerto
        # implicito.
        (
            "postgresql+asyncpg://app:secreto@prod.example.com/shifty?ssl=require",
            "postgresql://owner:otra@prod.example.com:5432/shifty",
        ),
    ],
)
def test_el_drill_no_restaura_sobre_la_base_de_origen(
    tmp_path: Path, monkeypatch: MonkeyPatch, origen: str, destino: str
) -> None:
    """AUD2-C-05 (2026-09-19): nada impedia restaurar sobre produccion.

    Sintoma: `_paso_restore` no comparaba DRILL_DATABASE_URL con la URL de
    origen. Con los dos secretos apuntando a la misma base -- un copy/paste al
    configurarlos -- el drill mensual, que corre solo por cron, ejecutaba
    `pg_restore --clean --if-exists` sobre produccion: DROP de cada objeto y
    recarga.
    """
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    backup_dir = tmp_path / "backups"
    evidence_dir = tmp_path / "evidence"
    _backup_en(backup_dir)

    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(backup_dir),
            "--evidence-dir",
            str(evidence_dir),
            "--run-restore",
            "--database-url",
            origen,
            "--restore-database-url",
            destino,
        ],
    )

    assert drill.main() == 1
    assert lanzados == [], "lanzo pg_restore contra la base de origen"

    evidencia = json.loads(next(evidence_dir.glob("drill-*.json")).read_text("utf-8"))
    assert evidencia["status"] == "failed"
    paso = next(p for p in evidencia["steps"] if p["name"] == "restore")
    assert "misma base" in paso["stderr"].lower() or "origen" in paso["stderr"].lower()
    # La URL no se filtra a la evidencia, que se sube como artifact.
    assert "secreto" not in json.dumps(evidencia)


def test_el_drill_restaura_cuando_el_destino_es_otra_base(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)

    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_restore_drill.py",
            "--backup-dir",
            str(backup_dir),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-restore",
            "--database-url",
            "postgresql://u:p@prod.example.com:5432/shifty",
            "--restore-database-url",
            "postgresql://u:p@drill.example.com:5432/shifty_drill",
        ],
    )

    assert drill.main() == 0
    assert any("restore_backup.py" in " ".join(c) for c in lanzados)


def _argv_de_restore(tmp_path: Path, backup_dir: Path) -> list[str]:
    return [
        "backup_restore_drill.py",
        "--backup-dir",
        str(backup_dir),
        "--evidence-dir",
        str(tmp_path / "evidence"),
        "--run-restore",
        "--database-url",
        "postgresql://u:p@prod.example.com:5432/shifty",
        "--restore-database-url",
        "postgresql://u:p@drill.example.com:5432/shifty_drill",
    ]


def _evidencia(tmp_path: Path) -> dict[str, object]:
    archivo = next((tmp_path / "evidence").glob("drill-*.json"))
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert isinstance(datos, dict)
    return datos


def test_el_drill_consulta_la_base_restaurada_y_lo_deja_en_la_evidencia(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """AUD2-C-04 (2026-09-19): el drill no miraba lo restaurado.

    Sintoma: escribia `status: ok` con el exit code de pg_restore y nada mas.
    Un dump valido de una base VACIA, o de la base equivocada, producia
    evidencia identica a la de un dump bueno; y el runbook usa esa evidencia
    para autorizar releases, prometiendo un health-check que nunca existio.
    """
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 0

    consulta = next(c for c in lanzados if c[0] == "psql")
    sql = consulta[-1]
    assert "alembic_version" in sql
    for tabla in ("stores", "appointments", "payments"):
        assert f"count(*) from {tabla}" in sql
    # La consulta va contra el DESTINO del drill, no contra el origen.
    assert "drill.example.com" in consulta

    evidencia = _evidencia(tmp_path)
    assert evidencia["status"] == "ok"
    assert evidencia["restored_alembic_version"] == "d2f4a6b8c0e2"
    assert evidencia["restored_rows"] == {
        "stores": "3",
        "appointments": "12",
        "payments": "5",
    }


def test_un_restore_sin_esquema_no_da_evidencia_ok(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Base vacia: alembic_version no devuelve nada.
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, _ = _drill_con_subprocess_falso(monkeypatch, verificacion=(0, "|0|0|0", ""))
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 1

    evidencia = _evidencia(tmp_path)
    assert evidencia["status"] == "failed"
    pasos = evidencia["steps"]
    assert isinstance(pasos, list)
    paso = next(p for p in pasos if p["name"] == "verify-restore")
    assert paso["ok"] is False
    assert "alembic_version" in paso["stderr"]


def test_una_tabla_critica_que_falta_no_da_evidencia_ok(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, _ = _drill_con_subprocess_falso(
        monkeypatch,
        verificacion=(1, "", 'ERROR:  relation "payments" does not exist'),
    )
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 1

    evidencia = _evidencia(tmp_path)
    assert evidencia["status"] == "failed"
    pasos = evidencia["steps"]
    assert isinstance(pasos, list)
    paso = next(p for p in pasos if p["name"] == "verify-restore")
    assert "does not exist" in paso["stderr"]


def test_si_la_guarda_frena_el_restore_no_se_verifica_nada(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # AUD2-C-05 + C-04: si el destino es el origen no se lanza nada, tampoco
    # la consulta de verificacion.
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    argv = _argv_de_restore(tmp_path, backup_dir)
    argv[-1] = "postgresql://u:p@prod.example.com:5432/shifty"
    monkeypatch.setattr("sys.argv", argv)

    assert drill.main() == 1
    assert lanzados == []
