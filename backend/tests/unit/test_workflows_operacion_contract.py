"""Workflows de operacion: imagenes versionadas (F0-02) y drill de backup (F0-20).

2026-09-24.
- Las imagenes se construian en el mismo VPS y sin version: no habia a que
  volver en un rollback (R11-02). `build-images.yml` las publica en GHCR con el
  sha del commit; `scripts/deploy.sh` solo hace `pull` de ese sha.
- El drill mensual fallo tres veces sin decir por que: los secretos estaban
  vacios y el error aparecia recien dentro de pg_dump (R11-17). Ahora el
  primer paso los verifica y falla con un mensaje que dice que falta.
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
