"""Contrato de `.pre-commit-config.yaml`: refleja el gate y dice como se activa.

C-22 (2026-09-19): el repo tiene DOS compuertas de pre-commit con el mismo
proposito -- `.githooks/pre-commit` (que necesita `git config core.hooksPath
.githooks`) y este archivo (que necesita `uv run pre-commit install`) -- y
ninguna esta activa: activar una desactiva la otra, porque `core.hooksPath`
deja de mirar `.git/hooks/`, que es donde `pre-commit install` escribe.

Este cambio NO activa ninguna: solo deja el archivo describiendo lo que hay
que saber antes de hacerlo. El test verifica que el YAML parsea, que los
hooks siguen cubriendo los mismos comandos que el gate (CLAUDE.md §6) y que
la documentacion de activacion sigue escrita.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
HOOK_MANUAL = REPO_ROOT / ".githooks" / "pre-commit"

# Los tres comandos del gate de backend (CLAUDE.md §6).
COMANDOS_DE_BACKEND = ("ruff format --check", "ruff check", "mypy")


def _entradas() -> list[str]:
    data: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [
        str(hook.get("entry", ""))
        for repo in data["repos"]
        for hook in repo.get("hooks", [])
    ]


def test_el_yaml_parsea_y_declara_hooks() -> None:
    assert CONFIG.exists(), "falta .pre-commit-config.yaml"
    assert _entradas(), "no declara ningun hook"


def test_cubre_los_tres_comandos_del_gate_de_backend() -> None:
    entradas = _entradas()
    for comando in COMANDOS_DE_BACKEND:
        assert any(comando in entrada for entrada in entradas), (
            f"ningun hook corre `{comando}`, que es parte del gate"
        )


def test_cubre_lo_mismo_que_npm_run_check() -> None:
    package = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    sub_scripts = re.findall(r"npm run ([\w:-]+)", package["scripts"]["check"])
    assert sub_scripts, "no se pudo leer el script `check` del front"

    entradas = _entradas()
    for script in sub_scripts:
        assert any(f"run {script}" in entrada for entrada in entradas), (
            f"`npm run check` corre {script} y ningun hook lo cubre"
        )


def test_documenta_como_se_activa_y_que_hoy_no_lo_esta() -> None:
    texto = CONFIG.read_text(encoding="utf-8")
    assert "uv run pre-commit install" in texto, "no dice como se activa"
    assert "core.hooksPath" in texto, "no explica el conflicto con el hook manual"
    assert "verify-toolchain" in texto
    # Las versiones concretas: activar con un Node fuera del conjunto
    # soportado bloquea todos los commits.
    assert "24.18.0" in texto and "26.5.0" in texto


def test_el_hook_manual_sigue_existiendo() -> None:
    # Mientras no se elija una sola compuerta, las dos conviven.
    assert HOOK_MANUAL.exists()
