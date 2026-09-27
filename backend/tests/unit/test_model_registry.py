"""El registro de modelos debe estar completo y alcanzar para el worker.

Regresion real: el worker de Celery importaba las tasks (Appointment,
Payment...) pero nunca Staff; SQLAlchemy fallaba al configurar los mappers
("expression 'StaffModel' failed to locate a name") y ninguna tarea podia
consultar la base. La suite no lo veia porque el proceso de pytest importa
la app entera.
"""

import os
import subprocess
import sys
from pathlib import Path

from core.model_registry import MODEL_MODULES, load_all_models

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _archivos_con_tabla() -> set[str]:
    encontrados: set[str] = set()
    for raiz in ("modules", "infrastructure"):
        for archivo in (BACKEND_ROOT / raiz).rglob("*.py"):
            if "__tablename__" not in archivo.read_text(encoding="utf-8"):
                continue
            relativo = archivo.relative_to(BACKEND_ROOT).with_suffix("")
            encontrados.add(".".join(relativo.parts))
    return encontrados


def test_todo_modelo_con_tabla_esta_en_el_registro() -> None:
    faltan = _archivos_con_tabla() - set(MODEL_MODULES)
    assert not faltan, f"Modelos fuera de core/model_registry.py: {sorted(faltan)}"
    sobran = set(MODEL_MODULES) - _archivos_con_tabla()
    assert not sobran, f"El registro lista modulos sin __tablename__: {sorted(sobran)}"


def test_load_all_models_importa_todo() -> None:
    cargados = load_all_models()
    assert set(cargados) == set(MODEL_MODULES)
    for name in MODEL_MODULES:
        assert name in sys.modules


def test_el_worker_puede_configurar_los_mappers_en_un_proceso_limpio() -> None:
    # Reproduce el arranque del worker: solo las tasks (via core.celery_app),
    # nada de routers. configure_mappers() resuelve todas las relaciones por
    # nombre o explota como explotaba en produccion.
    script = (
        "import modules.auth.tasks, modules.payments.tasks, modules.notifications.tasks\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "print('mappers-ok')\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr[-1500:]
    assert "mappers-ok" in resultado.stdout


def test_la_suite_de_integracion_no_mantiene_su_propia_lista_de_modelos() -> None:
    """Defecto real (2026-09-17, C-13): lista paralela en el conftest.

    `tests/integration/conftest.py` poblaba Base.metadata con trece
    `import modules.*.model  # noqa: F401` escritos a mano -- sin billing ni
    waitlist -- y despues corria `create_all`. Es exactamente la duplicacion
    que este modulo existe para evitar (`core/model_registry.py`: "worker,
    beat, alembic, scripts" deben llamar a load_all_models()). Hoy no se nota
    porque el conftest tambien hace `from main import app` y la app importa
    todos los routers; el dia que un modelo no cuelgue de un router, la suite
    de integracion crea las tablas a medias y nadie lo ve.
    """
    conftest = BACKEND_ROOT / "tests" / "integration" / "conftest.py"
    fuente = conftest.read_text(encoding="utf-8")

    importados_a_mano = [
        linea.strip()
        for linea in fuente.splitlines()
        if linea.startswith("import modules.") or linea.startswith("from modules.")
    ]
    assert not importados_a_mano, (
        "el conftest de integracion vuelve a listar modelos a mano en vez de "
        f"usar load_all_models(): {importados_a_mano}"
    )
    assert "load_all_models()" in fuente, (
        "el conftest de integracion debe poblar Base.metadata desde el registro"
    )
