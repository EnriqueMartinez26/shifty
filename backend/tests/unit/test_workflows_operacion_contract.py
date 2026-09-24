"""Workflows de operacion: imagenes versionadas (F0-02) y drill de backup (F0-20).

2026-09-24.
- Las imagenes se construian en el mismo VPS y sin version: no habia a que
  volver en un rollback (R11-02). `build-images.yml` las publica en GHCR con el
  sha del commit; `scripts/deploy.sh` solo hace `pull` de ese sha.
- El drill mensual fallo tres veces sin decir por que: los secretos estaban
  vacios y el error aparecia recien dentro de pg_dump (R11-17). Ahora el
  primer paso los verifica y falla con un mensaje que dice que falta.
- C-23: `security-scan.yml` busca vulnerabilidades conocidas en el lock de
  Python (pip-audit) y en las tres imagenes (Trivy). Solo sirve si un hallazgo
  pone el workflow en rojo y si las herramientas no entran al repo como
  dependencia.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.host_falso import BASH

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DRILL = WORKFLOWS / "monthly-backup-drill.yml"
BUILD = WORKFLOWS / "build-images.yml"
SCAN = WORKFLOWS / "security-scan.yml"
QUALITY = WORKFLOWS / "quality.yml"
SERVICIOS = ("backend", "frontend", "nginx")


def _yaml(ruta: Path) -> dict[Any, Any]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert isinstance(datos, dict)
    return datos


def _disparadores(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) lee la clave `on` como True.
    disparadores = workflow.get("on", workflow.get(True))
    assert isinstance(disparadores, dict)
    return disparadores


# --- drill ------------------------------------------------------------------


def _pasos_del_drill() -> list[dict[str, Any]]:
    pasos = _yaml(DRILL)["jobs"]["drill"]["steps"]
    assert isinstance(pasos, list)
    return pasos


def test_el_drill_verifica_los_secretos_antes_que_nada() -> None:
    pasos = _pasos_del_drill()
    primero = pasos[0]
    assert "run" in primero, "el primer paso del drill no es la verificacion"
    for secreto in ("BACKUP_DATABASE_URL", "DRILL_DATABASE_URL"):
        assert primero["env"][secreto] == f"${{{{ secrets.{secreto} }}}}"
    assert "::error" in primero["run"]


@pytest.mark.skipif(BASH is None, reason="hace falta bash")
@pytest.mark.parametrize(
    ("backup", "drill", "falta"),
    [
        ("", "", "BACKUP_DATABASE_URL DRILL_DATABASE_URL"),
        ("postgresql://o:x@db/shifty", "", "DRILL_DATABASE_URL"),
        ("", "postgresql://o:x@drill/shifty", "BACKUP_DATABASE_URL"),
    ],
)
def test_sin_secretos_el_drill_falla_diciendo_cuales_faltan(
    backup: str, drill: str, falta: str
) -> None:
    assert BASH is not None
    resultado = subprocess.run(
        [BASH, "-c", _pasos_del_drill()[0]["run"]],
        env={
            **os.environ,
            "BACKUP_DATABASE_URL": backup,
            "DRILL_DATABASE_URL": drill,
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 1
    assert f"Faltan los secretos del repo: {falta}." in resultado.stdout


@pytest.mark.skipif(BASH is None, reason="hace falta bash")
def test_con_los_secretos_el_drill_sigue() -> None:
    assert BASH is not None
    resultado = subprocess.run(
        [BASH, "-c", _pasos_del_drill()[0]["run"]],
        env={
            **os.environ,
            "BACKUP_DATABASE_URL": "postgresql://o:x@db/shifty",
            "DRILL_DATABASE_URL": "postgresql://o:x@drill/shifty_drill",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout


def test_el_drill_nunca_pasa_database_url() -> None:
    """DATABASE_URL es el rol de la app, con RLS: pg_dump con ese rol aborta o
    vuelca a medias. El drill usa el rol dueno por BACKUP_DATABASE_URL."""
    for paso in _pasos_del_drill():
        assert "DATABASE_URL" not in (paso.get("env") or {}), paso.get("name")


def test_el_drill_puede_correr_en_un_runner_propio() -> None:
    """Con `ports: !reset []` la base no se publica: ubuntu-latest no la ve."""
    runs_on = _yaml(DRILL)["jobs"]["drill"]["runs-on"]
    assert "vars.BACKUP_DRILL_RUNNER" in runs_on


# --- imagenes ---------------------------------------------------------------


def test_build_images_corre_en_main_y_a_mano() -> None:
    disparadores = _disparadores(_yaml(BUILD))
    assert disparadores["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in disparadores
    assert "pull_request" not in disparadores, "un PR no publica imagenes"


def test_build_images_publica_los_tres_servicios_por_sha() -> None:
    job = _yaml(BUILD)["jobs"]["build"]
    assert job["permissions"]["packages"] == "write"
    servicios = {item["service"] for item in job["strategy"]["matrix"]["include"]}
    assert servicios == set(SERVICIOS)

    paso = next(
        p
        for p in job["steps"]
        if str(p.get("uses", "")).startswith("docker/build-push-action@")
    )
    tags = paso["with"]["tags"]
    base = "ghcr.io/enriquemartinez26/shifty-${{ matrix.service }}"
    env = _yaml(BUILD)["env"]
    resuelto = tags.replace("${{ env.REGISTRY }}", env["REGISTRY"]).replace(
        "${{ env.OWNER }}", env["OWNER"]
    )
    assert f"{base}:${{{{ github.sha }}}}" in resuelto
    assert f"{base}:latest" in resuelto
    assert paso["with"]["push"] is True
    # Un manifiesto de attestation sin tag lo borraria la limpieza.
    assert paso["with"]["provenance"] is False


def test_las_acciones_de_build_images_van_por_version_exacta() -> None:
    """Mismo criterio que el resto de CI (dependabot las sube)."""
    for job in _yaml(BUILD)["jobs"].values():
        for paso in job["steps"]:
            uso = paso.get("uses")
            if uso:
                assert re.search(r"@v\d+\.\d+\.\d+$", uso), uso


# --- escaneo de vulnerabilidades (C-23) --------------------------------------


def _scan_jobs() -> dict[str, Any]:
    jobs = _yaml(SCAN)["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _paso(job: str, nombre: str) -> dict[str, Any]:
    return next(p for p in _scan_jobs()[job]["steps"] if p.get("name") == nombre)


def test_security_scan_corre_en_pr_main_cron_y_a_mano() -> None:
    disparadores = _disparadores(_yaml(SCAN))
    assert "pull_request" in disparadores
    assert disparadores["push"]["branches"] == ["main"]
    assert disparadores["schedule"] == [{"cron": "0 6 * * 1"}]
    assert "workflow_dispatch" in disparadores


def test_security_scan_tiene_los_tres_escaneos() -> None:
    jobs = _scan_jobs()
    assert {"python-audit", "image-scan", "npm-audit"} <= set(jobs)

    servicios = {
        i["service"] for i in jobs["image-scan"]["strategy"]["matrix"]["include"]
    }
    assert servicios == set(SERVICIOS)

    # En PR y push el npm audit es el de quality.yml; aca solo el cron y a mano.
    assert "schedule" in jobs["npm-audit"]["if"]
    assert "pull_request" not in jobs["npm-audit"]["if"]
    pasos_front = _yaml(QUALITY)["jobs"]["frontend-quality"]["steps"]
    assert any(
        "npm audit --omit=dev --audit-level=low" in str(p.get("run", ""))
        for p in pasos_front
    ), "quality.yml dejo de auditar el front: npm-audit ya no cubre los PR"


def test_un_hallazgo_pone_el_workflow_en_rojo() -> None:
    for nombre, job in _scan_jobs().items():
        assert "continue-on-error" not in job, nombre
        for paso in job["steps"]:
            assert "continue-on-error" not in paso, paso.get("name")
            assert "|| true" not in str(paso.get("run", "")), paso.get("name")

    trivy = _paso("image-scan", "Trivy")["with"]
    assert str(trivy["exit-code"]) == "1"
    assert set(trivy["severity"].split(",")) == {"CRITICAL", "HIGH"}
    assert set(trivy["vuln-type"].split(",")) == {"os", "library"}
    assert trivy["ignore-unfixed"] is True
    assert trivy["trivyignores"] == ".trivyignore"

    assert "--strict" in _paso("python-audit", "pip-audit")["run"]


def test_pip_audit_audita_exactamente_el_lock_de_produccion() -> None:
    exportar = _paso("python-audit", "Exportar las dependencias de produccion del lock")
    for bandera in ("uv export", "--frozen", "--no-dev", "--no-emit-project"):
        assert bandera in exportar["run"], bandera

    auditar = _paso("python-audit", "pip-audit")["run"]
    # Sin pip no resuelve nada: audita la lista con hashes tal cual sale del lock.
    assert "--disable-pip" in auditar and "--require-hashes" in auditar
    assert '-r "$RUNNER_TEMP/requirements-prod.txt"' in auditar
    assert "pip-audit==${PIP_AUDIT_VERSION}" in auditar
    assert re.fullmatch(r"\d+\.\d+\.\d+", _yaml(SCAN)["env"]["PIP_AUDIT_VERSION"])


@pytest.mark.skipif(BASH is None, reason="hace falta bash")
def test_las_excepciones_de_pip_audit_llegan_como_ignore_vuln(tmp_path: Path) -> None:
    (tmp_path / ".pip-audit-ignore").write_bytes(
        b"# encabezado\r\n\r\n# motivo\r\nPYSEC-2026-1  # al lado\r\n"
        b"# motivo\n  GHSA-abcd-efgh-ijkl"
    )
    # `uvx` falso: anota los argumentos que recibiria pip-audit.
    script = (
        'uvx() { printf "%s\n" "$@"; }\n' + _paso("python-audit", "pip-audit")["run"]
    )
    assert BASH is not None
    resultado = subprocess.run(
        [BASH, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": "/tmp", "PIP_AUDIT_VERSION": "2.10.1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    argumentos = resultado.stdout.splitlines()
    ignorados = [
        argumentos[i + 1] for i, a in enumerate(argumentos) if a == "--ignore-vuln"
    ]
    assert ignorados == ["PYSEC-2026-1", "GHSA-abcd-efgh-ijkl"]


@pytest.mark.parametrize(
    "archivo", [REPO_ROOT / "backend" / ".pip-audit-ignore", REPO_ROOT / ".trivyignore"]
)
def test_cada_excepcion_aceptada_lleva_su_motivo(archivo: Path) -> None:
    lineas = [
        linea.strip() for linea in archivo.read_text(encoding="utf-8").splitlines()
    ]
    for i, linea in enumerate(lineas):
        if linea and not linea.startswith("#"):
            assert i > 0 and lineas[i - 1].startswith("#"), (
                f"{archivo.name}: {linea} sin comentario de motivo arriba"
            )


def test_las_acciones_de_security_scan_van_fijadas() -> None:
    for job in _scan_jobs().values():
        for paso in job["steps"]:
            uso = paso.get("uses")
            if not uso or uso.startswith("./"):
                continue
            if uso.startswith("aquasecurity/"):
                # Sus tags se reescribieron alguna vez: solo sha completo.
                assert re.search(r"@[0-9a-f]{40}$", uso), uso
            else:
                assert re.search(r"@v\d+\.\d+\.\d+$", uso), uso


def test_las_herramientas_de_escaneo_no_entran_como_dependencia() -> None:
    """CLAUDE.md §1: pip-audit y Trivy corren desde CI, no desde el repo."""
    manifiestos = (
        REPO_ROOT / "backend" / "pyproject.toml",
        REPO_ROOT / "backend" / "uv.lock",
        REPO_ROOT / "frontend" / "package.json",
    )
    for manifiesto in manifiestos:
        texto = manifiesto.read_text(encoding="utf-8").lower()
        for herramienta in ("pip-audit", "pip_audit", "trivy"):
            assert herramienta not in texto, f"{herramienta} en {manifiesto.name}"
