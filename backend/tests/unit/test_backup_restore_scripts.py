from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
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
    # Drill 2026-09-24: con --no-privileges el dump no traia los GRANT a
    # shifty_app y la base restaurada le negaba todo a la app.
    assert "--no-privileges" not in command
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
    # Drill 2026-09-24: --no-privileges descartaba los GRANT y los default ACL
    # de shifty_app al restaurar; la app recibia "permission denied".
    assert "--no-privileges" not in command
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
    for clave in ("DATABASE_URL", "BACKUP_DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(clave, raising=False)
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


# Lo que devuelve la consulta de permisos del rol de la app cuando la base
# restaurada es usable por la app: sin superusuario ni BYPASSRLS, los tres
# timeouts de c2e4f6a8b0d1, USAGE en public, 42 tablas y ninguna tabla ni
# secuencia sin permisos.
TIMEOUTS_OK = (
    "statement_timeout=30s,lock_timeout=5s,idle_in_transaction_session_timeout=60s"
)
ROL_APP_OK = f"f|f|{TIMEOUTS_OK}|t|42||"


def _drill_con_subprocess_falso(
    monkeypatch: MonkeyPatch,
    verificacion: tuple[int, str, str] = (0, VERIFICACION_OK, ""),
    verificacion_app: tuple[int, str, str] = (0, ROL_APP_OK, ""),
) -> tuple[ModuleType, list[list[str]]]:
    drill = load_script("backup_restore_drill")
    lanzados: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        lanzados.append(list(command))
        if command and command[0] == "psql":
            es_de_permisos = "has_table_privilege" in command[-1]
            code, out, err = verificacion_app if es_de_permisos else verificacion
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


def test_el_directorio_de_backups_esta_ignorado_por_git() -> None:
    """AUD2-C-06 (2026-09-19): los dumps caian en un directorio versionable.

    El runbook y el workflow escriben en `backups/` de la raiz
    (`--output-dir ../backups`). Sin esa ruta en .gitignore, un `git add -A`
    despues de correr el drill local mete un dump completo -- datos de
    clientes, hashes, tokens de MP cifrados -- en el historial, de donde no se
    borra con un commit. gitleaks no lo atajaria: es un binario de pg_dump, no
    un patron de secreto.
    """
    repo_root = BACKEND_ROOT.parent
    for ruta in ("backups/shifty-20260621T120000Z.dump", "backups/evidence/x.json"):
        resultado = subprocess.run(
            ["git", "check-ignore", "-q", ruta],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert resultado.returncode == 0, f"git no ignora {ruta}"


# --- F0-20 (2026-09-24): el backup sale con el rol dueno, nunca con el de RLS --
#
# Sintoma: `backup_db.py` tomaba `DATABASE_URL` por defecto, que en compose es
# el rol `shifty_app`, sin BYPASSRLS. Con RLS activa `pg_dump` aborta ("query
# would be affected by row-level security policy") o, peor, vuelca solo lo que
# la politica deja ver. El workflow mensual ademas lo alimentaba con
# `DATABASE_URL: secrets.BACKUP_DATABASE_URL`, asi que el nombre del secreto no
# decia que rol esperaba.

URL_RLS = "postgresql+asyncpg://shifty_app:app_secret@db:5432/shifty_db?ssl=disable"
URL_DUENO = (
    "postgresql+asyncpg://shifty_user:owner_secret@db:5432/shifty_db?ssl=disable"
)
URL_BACKUP = "postgresql://backup_owner:backup_secret@db:5432/shifty_db?ssl=require"


@pytest.mark.parametrize(
    ("entorno", "esperada"),
    [
        (
            {"DATABASE_URL": URL_RLS, "MIGRATION_DATABASE_URL": URL_DUENO},
            URL_DUENO,
        ),
        (
            {
                "DATABASE_URL": URL_RLS,
                "MIGRATION_DATABASE_URL": URL_DUENO,
                "BACKUP_DATABASE_URL": URL_BACKUP,
            },
            URL_BACKUP,
        ),
        ({"DATABASE_URL": URL_RLS}, ""),
    ],
    ids=["migracion", "backup-gana", "solo-rls"],
)
def test_backup_db_toma_la_url_del_dueno_y_nunca_database_url(
    entorno: dict[str, str], esperada: str
) -> None:
    backup_db = load_script("backup_db")

    assert backup_db._default_database_url(entorno) == esperada


@pytest.mark.parametrize(
    "url",
    [
        URL_RLS,
        # Misma URL que DATABASE_URL aunque el usuario tenga otro nombre.
        "postgresql+asyncpg://otro_app:x@db:5432/shifty_db?ssl=disable",
    ],
    ids=["usuario-shifty_app", "igual-a-database-url"],
)
def test_backup_db_rechaza_el_rol_de_la_app_aunque_se_pase_explicito(
    url: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_db = load_script("backup_db")
    lanzados: list[list[str]] = []
    monkeypatch.setattr(
        backup_db.subprocess,
        "run",
        lambda command, **_: lanzados.append(list(command)),
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://otro_app:x@db:5432/shifty_db?ssl=disable",
    )
    monkeypatch.delenv("APP_DB_USER", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["backup_db.py", "--output-dir", str(tmp_path), "--database-url", url],
    )

    with pytest.raises(SystemExit) as salida:
        backup_db.main()

    assert "RLS" in str(salida.value)
    assert lanzados == [], "lanzo pg_dump con el rol de la app"
    # El mensaje no filtra credenciales (regla 20).
    assert "app_secret" not in str(salida.value)


def test_backup_db_sin_url_de_dueno_falla_nombrando_las_variables(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_db = load_script("backup_db")
    for clave in ("BACKUP_DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(clave, raising=False)
    monkeypatch.setenv("DATABASE_URL", URL_RLS)
    monkeypatch.setattr("sys.argv", ["backup_db.py", "--output-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as salida:
        backup_db.main()

    mensaje = str(salida.value)
    assert "BACKUP_DATABASE_URL" in mensaje
    assert "MIGRATION_DATABASE_URL" in mensaje


@pytest.mark.parametrize(
    ("url", "modo"),
    [
        (URL_DUENO, "disable"),
        (URL_BACKUP, "require"),
        (URL_DUENO.split("?")[0], "require"),
    ],
    ids=["ssl-disable", "ssl-require", "sin-nada-require"],
)
def test_backup_db_respeta_el_modo_tls_de_la_url(
    url: str, modo: str, tmp_path: Path
) -> None:
    """La URL del repo es de asyncpg (`?ssl=`): pg_dump lo ignoraba y usaba el
    default de libpq. Ahora se lee con `core.config.parse_db_url`, la misma
    lectura que las migraciones (regla 17)."""
    backup_db = load_script("backup_db")

    command, env = backup_db._build_pg_dump_command(url, tmp_path / "x.dump")

    assert env["PGSSLMODE"] == modo
    assert not any("ssl" in parte for parte in command)


def test_backup_db_decodifica_la_contrasena_de_la_url(tmp_path: Path) -> None:
    backup_db = load_script("backup_db")

    _, env = backup_db._build_pg_dump_command(
        "postgresql://dueno:p%40ss%2Fword@db:5432/shifty_db?ssl=disable",
        tmp_path / "x.dump",
    )

    assert env["PGPASSWORD"] == "p@ss/word"


def test_el_drill_tampoco_toma_database_url(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL_RLS)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", URL_DUENO)
    monkeypatch.delenv("BACKUP_DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["backup_restore_drill.py"])
    drill = load_script("backup_restore_drill")

    assert drill._parse_args().database_url == URL_DUENO


# --- Drill 2026-09-24: permisos de shifty_app en la base restaurada -----------
#
# Sintoma: backup_db.py volcaba y restore_backup.py restauraba con
# --no-privileges. La base restaurada quedaba con 0 GRANT y 0 default ACL para
# shifty_app: la app recibia "permission denied" en todas las tablas. El drill
# verificaba con el rol DUENO y daba "ok" sobre una base que la app no podia
# leer. Ademas, pg_restore --exit-on-error aborta en
# `GRANT USAGE ON SCHEMA public TO shifty_app` si el rol no existe en el
# destino, y los timeouts del rol (c2e4f6a8b0d1) no viajan en el dump.


def test_el_drill_verifica_los_permisos_del_rol_de_la_app(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    monkeypatch.delenv("APP_DB_USER", raising=False)
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 0

    consulta = next(
        c for c in lanzados if c[0] == "psql" and "has_table_privilege" in c[-1]
    )
    sql = consulta[-1]
    assert "drill.example.com" in consulta
    assert "has_schema_privilege('shifty_app', 'public', 'USAGE')" in sql
    # has_table_privilege con varios privilegios separados por coma da true si
    # tiene CUALQUIERA: cada uno se pregunta por separado.
    for privilegio in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert f"'{privilegio}')" in sql
    assert "rolbypassrls" in sql
    assert "rolconfig" in sql

    evidencia = _evidencia(tmp_path)
    assert evidencia["status"] == "ok"
    pasos = evidencia["steps"]
    assert isinstance(pasos, list)
    paso = next(p for p in pasos if p["name"] == "verify-app-role")
    assert paso["ok"] is True
    assert "shifty_app" in paso["stdout"]


def test_el_drill_usa_el_rol_de_app_db_user(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    monkeypatch.setenv("APP_DB_USER", "otra_app")
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 0

    sql = next(c for c in lanzados if "has_table_privilege" in c[-1])[-1]
    assert "'otra_app'" in sql
    assert "shifty_app" not in sql


@pytest.mark.parametrize(
    ("salida", "motivo"),
    [
        (f"f|t|{TIMEOUTS_OK}|t|42||", "BYPASSRLS"),
        (f"t|f|{TIMEOUTS_OK}|t|42||", "superusuario"),
        ("f|f||t|42||", "statement_timeout"),
        (
            "f|f|statement_timeout=30s,lock_timeout=5s|t|42||",
            "idle_in_transaction_session_timeout",
        ),
        (f"f|f|{TIMEOUTS_OK}|f|42||", "USAGE"),
        (f"f|f|{TIMEOUTS_OK}|t|42|appointments,payments|", "appointments,payments"),
        (f"f|f|{TIMEOUTS_OK}|t|42||appointments_seq", "appointments_seq"),
        (f"f|f|{TIMEOUTS_OK}|t|0||", "tablas"),
    ],
    ids=[
        "bypassrls",
        "superusuario",
        "sin-timeouts",
        "falta-un-timeout",
        "sin-usage-en-public",
        "tablas-sin-permisos",
        "secuencias-sin-permisos",
        "sin-tablas",
    ],
)
def test_una_base_que_la_app_no_puede_usar_no_da_evidencia_ok(
    tmp_path: Path, monkeypatch: MonkeyPatch, salida: str, motivo: str
) -> None:
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, _ = _drill_con_subprocess_falso(
        monkeypatch, verificacion_app=(0, salida, "")
    )
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 1

    evidencia = _evidencia(tmp_path)
    assert evidencia["status"] == "failed"
    pasos = evidencia["steps"]
    assert isinstance(pasos, list)
    paso = next(p for p in pasos if p["name"] == "verify-app-role")
    assert paso["ok"] is False
    assert motivo in paso["stderr"]


def test_un_restore_sin_el_rol_de_la_app_no_da_evidencia_ok(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, _ = _drill_con_subprocess_falso(
        monkeypatch,
        verificacion_app=(1, "", 'ERROR:  role "shifty_app" does not exist'),
    )
    monkeypatch.setattr("sys.argv", _argv_de_restore(tmp_path, backup_dir))

    assert drill.main() == 1

    evidencia = _evidencia(tmp_path)
    pasos = evidencia["steps"]
    assert isinstance(pasos, list)
    paso = next(p for p in pasos if p["name"] == "verify-app-role")
    assert paso["ok"] is False
    assert "does not exist" in paso["stderr"]


def test_el_drill_pasa_create_app_role_al_restore(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    _backup_en(backup_dir)
    drill, lanzados = _drill_con_subprocess_falso(monkeypatch)
    argv = [*_argv_de_restore(tmp_path, backup_dir), "--create-app-role"]
    monkeypatch.setattr("sys.argv", argv)

    assert drill.main() == 0

    restore = next(c for c in lanzados if "restore_backup.py" in " ".join(c))
    assert "--create-app-role" in restore


# --- restore_backup.py: el rol de la app existe ANTES de pg_restore ----------

URL_DESTINO = "postgresql://dueno:dueno_secret@drill.example.com:5432/shifty_drill"
# Valor de prueba con comilla, dos puntos y barra invertida: ejercita el escape
# del literal SQL.
CLAVE_APP = "clave-de-prueba-'con:rarezas\\x"


def _restore_con_subprocess_falso(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    rol_existe: bool,
    extra: list[str] | None = None,
) -> tuple[ModuleType, list[dict[str, object]]]:
    restore_backup = load_script("restore_backup")
    lanzados: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        lanzados.append({"command": list(command), "input": kwargs.get("input")})
        if command[0] == "psql" and "pg_roles" in " ".join(command):
            return SimpleNamespace(
                returncode=0, stdout="1\n" if rol_existe else "", stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(restore_backup.subprocess, "run", fake_run)
    dump = tmp_path / "shifty.dump"
    dump.write_bytes(b"fake custom dump")
    monkeypatch.setattr(
        "sys.argv",
        [
            "restore_backup.py",
            "--backup-file",
            str(dump),
            "--database-url",
            URL_DESTINO,
            *(extra or []),
        ],
    )
    return restore_backup, lanzados


def _comandos(lanzados: list[dict[str, object]]) -> list[list[str]]:
    comandos: list[list[str]] = []
    for lanzado in lanzados:
        command = lanzado["command"]
        assert isinstance(command, list)
        comandos.append(command)
    return comandos


def test_restore_se_niega_si_el_rol_de_la_app_no_existe(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_DB_USER", raising=False)
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=False
    )

    with pytest.raises(SystemExit) as salida:
        restore_backup.main()

    mensaje = str(salida.value)
    assert "shifty_app" in mensaje
    assert "--create-app-role" in mensaje
    comandos = _comandos(lanzados)
    assert not any(c[0] == "pg_restore" for c in comandos), (
        "lanzo pg_restore sin el rol: aborta a mitad y deja la base a medias"
    )
    consulta = next(c for c in comandos if c[0] == "psql")
    assert "rolname = 'shifty_app'" in consulta[-1]
    assert "drill.example.com" in consulta
    assert "dueno_secret" not in mensaje


def test_restore_con_el_rol_existente_restaura(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DB_USER", "otra_app")
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=True
    )

    assert restore_backup.main() == 0

    comandos = _comandos(lanzados)
    assert [c[0] for c in comandos] == ["psql", "pg_restore"]
    assert "rolname = 'otra_app'" in comandos[0][-1]


def test_restore_rechaza_un_nombre_de_rol_que_no_es_identificador(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DB_USER", "app'; drop table stores; --")
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=True
    )

    with pytest.raises(SystemExit) as salida:
        restore_backup.main()

    assert "APP_DB_USER" in str(salida.value)
    assert lanzados == []


def test_restore_create_app_role_crea_el_rol_con_sus_timeouts(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APP_DB_USER", raising=False)
    monkeypatch.setenv("APP_DB_PASSWORD", CLAVE_APP)
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=False, extra=["--create-app-role"]
    )

    assert restore_backup.main() == 0

    comandos = _comandos(lanzados)
    assert [c[0] for c in comandos] == ["psql", "psql", "pg_restore"]
    sql = lanzados[1]["input"]
    assert isinstance(sql, str)
    assert 'CREATE ROLE "shifty_app" LOGIN' in sql
    assert "NOSUPERUSER" in sql and "NOBYPASSRLS" in sql
    assert "ALTER ROLE \"shifty_app\" SET statement_timeout = '30s'" in sql
    assert "ALTER ROLE \"shifty_app\" SET lock_timeout = '5s'" in sql
    assert (
        "ALTER ROLE \"shifty_app\" SET idle_in_transaction_session_timeout = '60s'"
        in sql
    )
    # Literal escapado (comilla duplicada, barra invertida en E'') por stdin:
    # nunca en argv (visible en `ps`) ni en la salida.
    assert "E'clave-de-prueba-''con:rarezas\\\\x'" in sql
    assert not any("clave-de-prueba" in parte for parte in comandos[1])
    salida = capsys.readouterr()
    assert "clave-de-prueba" not in salida.out + salida.err


def test_restore_create_app_role_con_el_rol_existente_no_toca_la_clave(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_DB_USER", raising=False)
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=True, extra=["--create-app-role"]
    )

    assert restore_backup.main() == 0

    sql = lanzados[1]["input"]
    assert isinstance(sql, str)
    assert "CREATE ROLE" not in sql
    assert "PASSWORD" not in sql
    assert 'ALTER ROLE "shifty_app" NOSUPERUSER NOBYPASSRLS' in sql
    assert "statement_timeout = '30s'" in sql


def test_restore_create_app_role_sin_app_db_password_no_crea_nada(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=False, extra=["--create-app-role"]
    )

    with pytest.raises(SystemExit) as salida:
        restore_backup.main()

    assert "APP_DB_PASSWORD" in str(salida.value)
    assert [c[0] for c in _comandos(lanzados)] == ["psql"]


def test_restore_create_app_role_no_toca_al_usuario_de_la_conexion(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Revision 2026-09-24: con APP_DB_USER igual al usuario de la URL destino
    (el superusuario del cluster), --create-app-role le aplicaba
    `ALTER ROLE ... NOSUPERUSER NOBYPASSRLS` al propio superusuario de
    arranque y dejaba el cluster sin quien lo administre."""
    monkeypatch.setenv("APP_DB_USER", "dueno")
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=True, extra=["--create-app-role"]
    )

    with pytest.raises(SystemExit) as salida:
        restore_backup.main()

    mensaje = str(salida.value)
    assert "dueno" in mensaje
    assert "superusuario" in mensaje
    assert "dueno_secret" not in mensaje
    assert lanzados == [], "lanzo psql contra el usuario de la conexion"


def test_restore_no_filtra_la_clave_si_psql_falla_al_crear_el_rol(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", CLAVE_APP)
    restore_backup, lanzados = _restore_con_subprocess_falso(
        monkeypatch, tmp_path, rol_existe=False, extra=["--create-app-role"]
    )
    original = restore_backup.subprocess.run

    def falla_al_crear(command: list[str], **kwargs: object) -> SimpleNamespace:
        resultado: SimpleNamespace = original(command, **kwargs)
        entrada = kwargs.get("input")
        if entrada:
            # psql repite la linea que fallo en el error (LINE 1: ...).
            return SimpleNamespace(
                returncode=3, stdout="", stderr=f"ERROR:  boom\nLINE 1: {entrada}"
            )
        return resultado

    monkeypatch.setattr(restore_backup.subprocess, "run", falla_al_crear)

    with pytest.raises(SystemExit) as salida:
        restore_backup.main()

    capturado = capsys.readouterr()
    todo = str(salida.value) + capturado.out + capturado.err
    assert "boom" in todo
    assert "clave-de-prueba" not in todo
    assert not any(c[0] == "pg_restore" for c in _comandos(lanzados))
