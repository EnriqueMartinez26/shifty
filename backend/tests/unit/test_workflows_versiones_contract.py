"""Contrato: las versiones del toolchain viven en UN lugar por herramienta.

Defecto real (2026-09-18, C-21): `monthly-backup-drill.yml` hardcodeaba
`python-version: "3.14.6"` y `version: "0.11.29"`, y `e2e.yml` repetia
`NODE_VERSION`/`NPM_VERSION`: los mismos valores que `quality.yml` define como
`env`. Un bump en `quality.yml` dejaba atras a los otros en silencio; el
proyecto ya pago esa deriva de toolchain (CLAUDE.md §5).

Python y uv: la unica fuente es la composite action
`.github/actions/setup-python-uv`. Ningun workflow usa `setup-python` ni
`setup-uv` directo. Node y npm: `quality.yml` sigue siendo la fuente (sus
pasos son de los jobs del front) y `e2e.yml` tiene que coincidir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
COMPOSITE = REPO_ROOT / ".github" / "actions" / "setup-python-uv" / "action.yml"
USO_COMPOSITE = "./.github/actions/setup-python-uv"


def _yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _pasos_por_job() -> list[tuple[str, str, list[dict[str, Any]]]]:
    jobs: list[tuple[str, str, list[dict[str, Any]]]] = []
    for archivo in sorted(WORKFLOWS.glob("*.yml")):
        for nombre, job in (_yaml(archivo).get("jobs") or {}).items():
            pasos = [p for p in job.get("steps", []) if isinstance(p, dict)]
            jobs.append((archivo.name, str(nombre), pasos))
    return jobs


def _defaults_de_la_composite() -> dict[str, str]:
    data = _yaml(COMPOSITE)
    assert data["runs"]["using"] == "composite"
    return {
        nombre: str(entrada["default"]) for nombre, entrada in data["inputs"].items()
    }


def test_ningun_workflow_configura_python_ni_uv_por_su_cuenta() -> None:
    assert COMPOSITE.exists(), "falta la composite action setup-python-uv"
    directos = [
        f"{archivo}:{job}"
        for archivo, job, pasos in _pasos_por_job()
        for paso in pasos
        if str(paso.get("uses", "")).startswith(
            ("actions/setup-python@", "astral-sh/setup-uv@")
        )
    ]
    assert not directos, (
        f"configuran python/uv con su propia version en vez de la composite: {directos}"
    )


def test_todo_job_que_usa_uv_pasa_antes_por_la_composite() -> None:
    for archivo, job, pasos in _pasos_por_job():
        usa_uv = [
            i
            for i, p in enumerate(pasos)
            if re.search(r"\buv\b", str(p.get("run", "")))
        ]
        if not usa_uv:
            continue
        composite = [i for i, p in enumerate(pasos) if p.get("uses") == USO_COMPOSITE]
        assert composite and composite[0] < usa_uv[0], (
            f"{archivo}:{job} corre uv sin haber pasado por {USO_COMPOSITE}"
        )
        checkout = [
            i
            for i, p in enumerate(pasos)
            if str(p.get("uses", "")).startswith("actions/checkout@")
        ]
        # Una action local solo existe despues del checkout.
        assert checkout and checkout[0] < composite[0], (
            f"{archivo}:{job} usa la composite antes del checkout"
        )


def test_la_imagen_usa_las_mismas_versiones_que_ci() -> None:
    defaults = _defaults_de_la_composite()
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert f"FROM python:{defaults['python-version']}-" in dockerfile
    assert f"ghcr.io/astral-sh/uv:{defaults['uv-version']} " in dockerfile


def test_e2e_usa_la_misma_version_de_node_y_npm_que_quality() -> None:
    quality = _yaml(WORKFLOWS / "quality.yml")["env"]
    e2e = _yaml(WORKFLOWS / "e2e.yml")["env"]
    for clave in ("NODE_VERSION", "NPM_VERSION"):
        assert e2e.get(clave) == quality.get(clave), (
            f"e2e.yml {clave}={e2e.get(clave)!r} y quality.yml "
            f"{clave}={quality.get(clave)!r}"
        )
