"""El modelo de presupuestos sale del codigo; la tabla `budgets` NO (X-04).

2026-09-19, primer paso de X-04 (decision del coordinador: en dos pasos, para
no mezclar borrado de codigo con borrado de datos). `modules/budget/model.py`
era un modelo huerfano: ningun router, servicio, schema, repositorio ni
endpoint lo usaba. Solo lo sostenian el registro de modelos, el seed de
simulacion y tres tests que lo importaban para poblar `Base.metadata`.

La tabla `budgets` y sus politicas RLS siguen en la base: borrarlas es una
migracion aparte, recien cuando el usuario confirme que produccion tiene cero
filas. Por eso este test tambien exige el aviso en `core/model_registry.py`:
sin el modelo en el metadata, un `alembic revision --autogenerate` propone
`op.drop_table("budgets")`, y aceptarlo sin querer borra datos de produccion.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from core.model_registry import MODEL_MODULES, load_all_models
from core.models import Base

BACKEND = Path(__file__).resolve().parents[2]
REGISTRO = BACKEND / "core" / "model_registry.py"


def test_el_modelo_no_esta_en_el_arbol_de_git() -> None:
    """Lo que importa es el archivo versionado, no si el nombre del paquete
    resuelve: una carpeta vacia con `__pycache__` la resuelve igual como
    paquete de espacio de nombres (2026-09-19, gate de integracion)."""
    versionados = subprocess.run(
        ["git", "ls-files", "modules/budget"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert versionados == []


def test_el_modelo_no_se_puede_importar() -> None:
    sys.modules.pop("modules.budget.model", None)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("modules.budget.model")


def test_el_registro_no_lista_el_modulo_de_presupuestos() -> None:
    assert "modules.budget.model" not in MODEL_MODULES


def test_el_metadata_no_incluye_la_tabla_budgets() -> None:
    load_all_models()

    assert "budgets" not in Base.metadata.tables


def test_el_registro_avisa_que_la_tabla_sigue_en_la_base() -> None:
    """Sin este aviso, un autogenerate propone borrar la tabla y sus datos."""
    fuente = REGISTRO.read_text(encoding="utf-8")

    assert "budgets" in fuente
    assert "autogenerate" in fuente


def test_el_seed_de_simulacion_no_crea_presupuestos() -> None:
    fuente = (BACKEND / "scripts" / "seed_simulation.py").read_text(encoding="utf-8")

    assert "Budget" not in fuente
    assert "budgets" not in fuente
