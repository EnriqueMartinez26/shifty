"""Cada excepcion de `per-file-ignores` tiene que seguir haciendo falta.

Defecto real (2026-09-18, C-18): `"alembic/env.py" = ["F401"]` sobrevivia en
pyproject.toml aunque ya no quedaba ningun import por efecto secundario en
alembic/env.py: los tres simbolos que importa se usan. Una excepcion muerta
no protege nada y habilita en silencio el proximo import sin uso en ese
archivo. El job `dead-code` mira F401/F811 en archivos, no excepciones
huerfanas, asi que nadie lo veia. El mismo contrato encontro dos mas de la
misma clase (`modules/appointments/model.py` y `modules/users/model.py`, F401:
los re-exports por `__all__` ya no lo disparan) y se borraron en el mismo
cambio.

Mecanica: para cada entrada se corre ruff con `--isolated` (sin la config
del proyecto, o sea sin la excepcion) y solo con los codigos exceptuados. Si
no hay ningun hallazgo, la excepcion esta muerta.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _entradas() -> list[tuple[str, list[str]]]:
    data = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = data["tool"]["ruff"]["lint"]["per-file-ignores"]
    return sorted((str(glob), list(codes)) for glob, codes in ignores.items())


@pytest.mark.parametrize(
    ("glob", "codes"), _entradas(), ids=[glob for glob, _ in _entradas()]
)
def test_la_excepcion_todavia_hace_falta(glob: str, codes: list[str]) -> None:
    archivos = sorted(str(p) for p in BACKEND_ROOT.glob(glob) if p.is_file())
    assert archivos, f"per-file-ignores apunta a {glob!r}, que no existe"

    resultado = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--no-cache",
            "--exit-zero",
            "--output-format",
            "json",
            "--select",
            ",".join(codes),
            *archivos,
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    hallazgos = json.loads(resultado.stdout or "[]")
    assert hallazgos, (
        f"per-file-ignores {glob!r} = {codes} esta muerta: sin la excepcion ruff "
        "no encuentra nada. Borrala de pyproject.toml."
    )
