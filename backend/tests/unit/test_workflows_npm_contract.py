"""Contrato de los workflows: `npm ci` corre con la version de npm fijada.

Defecto real (2026-09-17, C-15): `.github/workflows/e2e.yml` corria
`npm ci` sin el paso `npm install --global npm@...` que sus cuatro
hermanos de `quality.yml` si tienen. `frontend/.npmrc` fija
`engine-strict=true` y `frontend/package.json` acota npm a
"11.16.0 || 11.17.0": si el npm que trae la imagen de node no es uno de
esos, `npm ci` aborta con EBADENGINE. CLAUDE.md §5 documenta ese modo de
fallo con fecha.
"""

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _pasos(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [paso for paso in job.get("steps", []) if isinstance(paso, dict)]


def _jobs_con_npm_ci() -> list[tuple[str, str, list[dict[str, Any]]]]:
    encontrados: list[tuple[str, str, list[dict[str, Any]]]] = []
    for archivo in sorted(WORKFLOWS.glob("*.yml")):
        data = yaml.safe_load(archivo.read_text(encoding="utf-8"))
        for nombre, job in (data.get("jobs") or {}).items():
            pasos = _pasos(job)
            if any("npm ci" in str(paso.get("run", "")) for paso in pasos):
                encontrados.append((archivo.name, str(nombre), pasos))
    return encontrados


def test_todo_job_que_hace_npm_ci_fija_antes_la_version_de_npm() -> None:
    jobs = _jobs_con_npm_ci()
    assert jobs, "ningun workflow corre `npm ci`: el contrato quedo sin sujeto"

    for archivo, nombre, pasos in jobs:
        indice_ci = next(
            i for i, paso in enumerate(pasos) if "npm ci" in str(paso.get("run", ""))
        )
        anteriores = [str(paso.get("run", "")) for paso in pasos[:indice_ci]]
        assert any(
            "npm install --global" in run and "npm@" in run for run in anteriores
        ), (
            f"{archivo}:{nombre} corre `npm ci` sin fijar npm antes; con "
            "engine-strict=true eso aborta con EBADENGINE"
        )


def test_el_front_sigue_exigiendo_la_version_declarada() -> None:
    # Si engine-strict se afloja, el contrato de arriba pierde su motivo.
    npmrc = (REPO_ROOT / "frontend" / ".npmrc").read_text(encoding="utf-8")
    assert "engine-strict=true" in npmrc
