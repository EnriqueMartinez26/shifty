"""Los scripts que usan la base cargan el registro COMPLETO de modelos.

Defecto real (2026-09-17, C-14): `scripts/bootstrap_superadmin.py` y
`scripts/seed_simulation.py` importaban a mano el subconjunto de modelos que
cada uno usa (el seed, 22 lineas; el bootstrap, dos). Ninguno llamaba a
`load_all_models()`, que es exactamente lo que
`core/model_registry.py` exige por escrito para "worker, beat, alembic,
scripts". Funcionaban por casualidad: las relaciones declaradas por nombre
que resuelven hoy estaban cubiertas por los modelos que si importaban.
Sintoma del dia en que deje de estarlo (p. ej. un
`relationship("WaitlistEntry")` en `User`): el script muere en su primera
query con "expression 'WaitlistEntry' failed to locate a name".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.model_registry import MODEL_MODULES

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Scripts que abren una sesion contra la base (los de pg_dump/pg_restore y el
# de carga por HTTP no tocan el ORM).
SCRIPTS_CON_ORM = ("bootstrap_superadmin", "seed_simulation")


def _modulos_cargados_por(script: str) -> set[str]:
    """Importa el script en un proceso limpio y devuelve los modelos cargados."""
    codigo = (
        "import importlib.util, json, sys\n"
        f"ruta = r'{BACKEND_ROOT / 'scripts'}' + '/{script}.py'\n"
        f"spec = importlib.util.spec_from_file_location('{script}', ruta)\n"
        "modulo = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(modulo)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=BACKEND_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND_ROOT),
            # seed_simulation exige DATABASE_URL al importarse.
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/d",
        },
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    return set(json.loads(resultado.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("script", SCRIPTS_CON_ORM)
def test_el_script_carga_todos_los_modelos(script: str) -> None:
    faltan = set(MODEL_MODULES) - _modulos_cargados_por(script)
    assert not faltan, (
        f"scripts/{script}.py arma su propio subconjunto de modelos en vez de "
        f"llamar a load_all_models(); no carga: {sorted(faltan)}"
    )
