from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Raiz del backend derivada del propio archivo: el drill se invoca tanto con
# `working-directory: backend` (workflow mensual) como desde la raiz del repo,
# y las rutas de los scripts que lanza no pueden depender del cwd.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.backup_db import _default_database_url, _sha256_file  # noqa: E402
from scripts.restore_backup import (  # noqa: E402
    TIMEOUTS_DEL_ROL_APP,
    _build_psql_command,
    _rol_de_la_app,
)


def _run(
    command: list[str], *, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=BACKEND_ROOT,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _latest_backup(backup_dir: Path) -> Path | None:
    backups = sorted(backup_dir.glob("shifty-*.dump"), reverse=True)
    return backups[0] if backups else None


def _verify_checksum(dump: Path, checksum_file: Path) -> tuple[bool, str]:
    """Compara el sha256 real del dump con el que escribio backup_db.py
    (`<hex>  <nombre>`). Sin archivo de checksum no hay nada que validar: falla."""
    if not checksum_file.exists():
        return False, f"No se encontro checksum para validar: {checksum_file}"
    parts = checksum_file.read_text(encoding="utf-8").split()
    expected = parts[0] if parts else ""
    actual = _sha256_file(dump)
    if actual != expected:
        return False, f"Checksum distinto: esperado {expected}, calculado {actual}"
    return True, f"sha256 verificado: {actual}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta drill de backup+restore y guarda evidencia JSON."
    )
    parser.add_argument("--backup-dir", default="backups", help="Directorio de backups")
    parser.add_argument(
        "--evidence-dir", default="backups/evidence", help="Directorio de evidencias"
    )
    # Rol DUENO, nunca DATABASE_URL (rol de la app, con RLS): F0-20.
    parser.add_argument(
        "--database-url",
        default=_default_database_url(os.environ),
        help="URL del rol dueno (BACKUP_DATABASE_URL o MIGRATION_DATABASE_URL)",
    )
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
    parser.add_argument(
        "--create-app-role",
        action="store_true",
        help=(
            "Pasa --create-app-role a restore_backup.py: crea el rol de la app "
            "en el destino si falta (necesita APP_DB_PASSWORD)"
        ),
    )
    return parser.parse_args()


def _add_step(
    evidence: dict[str, Any],
    name: str,
    ok: bool,
    stdout: str = "",
    stderr: str = "",
) -> None:
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


def _paso_backup(
    args: argparse.Namespace, backup_dir: Path, evidence: dict[str, Any]
) -> None:
    if not args.database_url:
        _add_step(
            evidence,
            "backup",
            False,
            stderr=(
                "BACKUP_DATABASE_URL (o MIGRATION_DATABASE_URL) no configurado: "
                "el backup va con el rol dueno, no con DATABASE_URL"
            ),
        )
        return
    code, out, err = _run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "backup_db.py"),
            "--output-dir",
            str(backup_dir.resolve()),
            "--database-url",
            args.database_url,
        ]
    )
    _add_step(evidence, "backup", code == 0, out, err)


def _paso_verificar_checksum(backup_dir: Path, evidence: dict[str, Any]) -> Path | None:
    """Ubica el ultimo dump y compara su sha256; devuelve el dump o None."""
    latest = _latest_backup(backup_dir)
    if not latest:
        _add_step(
            evidence,
            "locate-backup",
            False,
            stderr="No se encontro backup para validar",
        )
        return None
    evidence["backup_file"] = str(latest)
    checksum_file = latest.with_suffix(".sha256")
    if checksum_file.exists():
        evidence["checksum_file"] = str(checksum_file)
    # El .sha256 se recalcula y compara: registrar solo su ruta dejaba un
    # dump truncado con evidencia "ok" (C-06, 2026-09-17).
    ok, detail = _verify_checksum(latest, checksum_file)
    _add_step(
        evidence,
        "verify-checksum",
        ok,
        stdout=detail if ok else "",
        stderr="" if ok else detail,
    )
    return latest


def _mismo_destino(una: str, otra: str) -> bool:
    """Si las dos URLs apuntan a la misma base, sin mirar credenciales.

    Compara host, puerto (5432 si no esta) y nombre de base. El driver
    (`+asyncpg`), el usuario y los parametros de la query no cuentan: el
    peligro es el destino fisico.
    """

    def destino(url: str) -> tuple[str, int, str]:
        partes = urlsplit(url)
        return (
            (partes.hostname or "").lower(),
            partes.port or 5432,
            partes.path.lstrip("/"),
        )

    return destino(una) == destino(otra)


def _paso_restore(
    args: argparse.Namespace, latest: Path | None, evidence: dict[str, Any]
) -> None:
    if not latest:
        _add_step(evidence, "restore", False, stderr="No hay backup para restore")
        return
    if not args.restore_database_url:
        _add_step(
            evidence, "restore", False, stderr="DRILL_DATABASE_URL no configurado"
        )
        return
    # `pg_restore --clean --if-exists` dropea cada objeto antes de recargarlo:
    # contra la base de origen es un borrado de produccion, y este drill corre
    # solo, por cron, sin revision humana (AUD2-C-05, 2026-09-19).
    if args.database_url and _mismo_destino(
        args.database_url, args.restore_database_url
    ):
        _add_step(
            evidence,
            "restore",
            False,
            stderr=(
                "DRILL_DATABASE_URL apunta a la misma base que el origen "
                "(mismo host, puerto y nombre): pg_restore --clean la borraria. "
                "El destino del drill tiene que ser una base aparte."
            ),
        )
        return
    command = [
        sys.executable,
        str(BACKEND_ROOT / "scripts" / "restore_backup.py"),
        "--backup-file",
        str(latest.resolve()),
        "--database-url",
        args.restore_database_url,
    ]
    if args.create_app_role:
        command.append("--create-app-role")
    code, out, err = _run(command)
    _add_step(evidence, "restore", code == 0, out, err)


# Lo que se le pregunta a la base restaurada. Un dump de una base vacia, o de
# la base equivocada, producia evidencia "ok" identica a la de un dump bueno
# (AUD2-C-04): sin alembic_version no hay esquema, y las tablas criticas tienen
# que existir o psql corta con ON_ERROR_STOP.
TABLAS_CRITICAS = ("stores", "appointments", "payments")
_SQL_VERIFICACION = (
    "select (select version_num from alembic_version limit 1), "
    + ", ".join(f"(select count(*) from {tabla})" for tabla in TABLAS_CRITICAS)
)


def _paso_verificar_restore(args: argparse.Namespace, evidence: dict[str, Any]) -> None:
    """Consulta la base restaurada: el runbook promete health-check como evidencia."""
    command, env = _build_psql_command(args.restore_database_url, _SQL_VERIFICACION)
    code, out, err = _run(command, env=env)
    if code != 0:
        _add_step(evidence, "verify-restore", False, out, err)
        return

    campos = out.strip().split("|")
    version = campos[0] if campos else ""
    if not version:
        _add_step(
            evidence,
            "verify-restore",
            False,
            stderr=(
                "la base restaurada no tiene alembic_version: el dump no trae "
                "esquema o es de otra base"
            ),
        )
        return

    filas = dict(zip(TABLAS_CRITICAS, campos[1:]))
    evidence["restored_alembic_version"] = version
    evidence["restored_rows"] = filas
    _add_step(
        evidence,
        "verify-restore",
        True,
        stdout=f"alembic_version={version} filas={filas}",
    )


# Drill 2026-09-24: verificar con el rol DUENO daba "ok" sobre una base que la
# app no podia leer (el restore con --no-privileges la dejaba sin GRANT). Esta
# consulta pregunta por los permisos del ROL DE LA APP, tabla por tabla.
# has_table_privilege con varios privilegios separados por coma devuelve true
# si tiene CUALQUIERA: cada uno va por separado.
_PRIVILEGIOS_DE_TABLA = ("SELECT", "INSERT", "UPDATE", "DELETE")
_PRIVILEGIOS_DE_SECUENCIA = ("USAGE", "SELECT")
_RELACIONES_DE_PUBLIC = (
    "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
    "where n.nspname = 'public' and c.relkind"
)


def _sql_permisos_del_rol(rol: str) -> str:
    literal = f"'{rol}'"
    de_tabla = " and ".join(
        f"has_table_privilege({literal}, c.oid, '{p}')" for p in _PRIVILEGIOS_DE_TABLA
    )
    de_secuencia = " and ".join(
        f"has_sequence_privilege({literal}, c.oid, '{p}')"
        for p in _PRIVILEGIOS_DE_SECUENCIA
    )
    return (
        "select "
        f"(select rolsuper from pg_roles where rolname = {literal}), "
        f"(select rolbypassrls from pg_roles where rolname = {literal}), "
        "(select array_to_string(rolconfig, ',') from pg_roles "
        f"where rolname = {literal}), "
        f"has_schema_privilege({literal}, 'public', 'USAGE'), "
        f"(select count(*) {_RELACIONES_DE_PUBLIC} in ('r', 'p')), "
        "(select string_agg(c.relname, ',' order by c.relname) "
        f"{_RELACIONES_DE_PUBLIC} in ('r', 'p') and not ({de_tabla})), "
        "(select string_agg(c.relname, ',' order by c.relname) "
        f"{_RELACIONES_DE_PUBLIC} = 'S' and not ({de_secuencia}))"
    )


def _problemas_del_rol(rol: str, campos: list[str]) -> list[str]:
    superusuario, bypassrls, config, usage, tablas, sin_tabla, sin_seq = campos
    problemas: list[str] = []
    if superusuario != "f":
        problemas.append(f"{rol} es superusuario: saltea RLS")
    if bypassrls != "f":
        problemas.append(f"{rol} tiene BYPASSRLS: saltea RLS")
    ajustes = dict(par.split("=", 1) for par in config.split(",") if "=" in par)
    for parametro, valor in TIMEOUTS_DEL_ROL_APP:
        if ajustes.get(parametro) != valor:
            problemas.append(
                f"falta {parametro}={valor} en rolconfig de {rol} "
                "(ALTER ROLE ... SET, migracion c2e4f6a8b0d1)"
            )
    if usage != "t":
        problemas.append(f"{rol} no tiene USAGE en el esquema public")
    if not tablas.isdigit() or int(tablas) == 0:
        problemas.append("no hay tablas en public")
    if sin_tabla:
        problemas.append(
            f"tablas sin SELECT/INSERT/UPDATE/DELETE para {rol}: {sin_tabla}"
        )
    if sin_seq:
        problemas.append(f"secuencias sin USAGE/SELECT para {rol}: {sin_seq}")
    return problemas


def _paso_verificar_rol_app(args: argparse.Namespace, evidence: dict[str, Any]) -> None:
    """Que la APP pueda usar la base restaurada, no solo el dueno."""
    try:
        rol = _rol_de_la_app(os.environ)
    except ValueError as exc:
        _add_step(evidence, "verify-app-role", False, stderr=str(exc))
        return
    command, env = _build_psql_command(
        args.restore_database_url, _sql_permisos_del_rol(rol)
    )
    code, out, err = _run(command, env=env)
    if code != 0:
        _add_step(evidence, "verify-app-role", False, out, err)
        return

    campos = out.strip().split("|")
    if len(campos) != 7:
        _add_step(
            evidence,
            "verify-app-role",
            False,
            stderr=f"salida inesperada de la consulta de permisos: {out!r}",
        )
        return
    problemas = _problemas_del_rol(rol, campos)
    if problemas:
        _add_step(evidence, "verify-app-role", False, stderr="; ".join(problemas))
        return
    evidence["restored_app_role"] = rol
    _add_step(
        evidence,
        "verify-app-role",
        True,
        stdout=(
            f"{rol}: sin superusuario ni BYPASSRLS, timeouts en rolconfig, USAGE "
            f"en public y permisos en las {campos[4]} tablas y sus secuencias"
        ),
    )


def main() -> int:
    args = _parse_args()

    started_at = datetime.now(timezone.utc)
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    evidence: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "status": "ok",
        "steps": [],
    }

    if args.run_backup:
        _paso_backup(args, backup_dir, evidence)

    latest = _paso_verificar_checksum(backup_dir, evidence)

    if args.run_restore:
        _paso_restore(args, latest, evidence)
        # Solo si el restore salio bien: si fallo, o si la guarda lo freno, no
        # hay nada que verificar.
        if evidence["steps"][-1]["name"] == "restore" and evidence["steps"][-1]["ok"]:
            _paso_verificar_restore(args, evidence)
            _paso_verificar_rol_app(args, evidence)

    finished_at = datetime.now(timezone.utc)
    evidence["finished_at"] = finished_at.isoformat()
    evidence["duration_seconds"] = int((finished_at - started_at).total_seconds())

    evidence_path = evidence_dir / f"drill-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(f"Evidencia generada: {evidence_path}")
    return 0 if evidence.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
