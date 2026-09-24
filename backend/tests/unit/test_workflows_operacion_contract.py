"""Workflows de operacion: drill de backup (F0-20).

2026-09-24.
- El drill mensual fallo tres veces sin decir por que: los secretos estaban
  vacios y el error aparecia recien dentro de pg_dump (R11-17). Ahora el
  primer paso los verifica y falla con un mensaje que dice que falta.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.host_falso import BASH

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DRILL = WORKFLOWS / "monthly-backup-drill.yml"


def _yaml(ruta: Path) -> dict[Any, Any]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert isinstance(datos, dict)
    return datos


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
