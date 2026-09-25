"""Los eventos de la API salen etiquetados `component="api"`, no `"worker"`.

AUD2-B7-04 (2026-09-20). `core/celery_app.py` llamaba a
`init_observability("worker")` a nivel de modulo, y el proceso de la API
importa ese modulo mucho antes de su propia inicializacion, por la cadena
`main` -> `modules.appointment_blocks.router` -> `...service` ->
`modules.notifications.tasks` -> `core.celery_app`. Como `init_observability`
tiene un guard global `_initialized`, el `init_observability("api")` de
`main.py` retornaba sin hacer nada y TODOS los eventos de la API quedaban
etiquetados `component="worker"`.

Ese tag es la unica senal para separar "reventó un request" de "reventó un
job" en el dashboard de Sentry: con todo como `worker`, la primera pregunta de
cualquier incidente se responde mal. Efecto lateral: el proceso de la API
ademas ejecutaba `load_all_models()` y registraba los handlers de
`worker_init`/`beat_init`, carga que no le corresponde.

El arranque se observa en un proceso LIMPIO: dentro de la suite los modulos ya
estan importados y el orden real no se puede reproducir.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import core.celery_app as celery_app

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Espia el init ANTES de importar nada del arranque: `from core.observability
# import init_observability` de cada modulo levanta ya el doble.
_ESPIA = (
    "import json\n"
    "import core.observability as obs\n"
    "llamados = []\n"
    "obs.init_observability = lambda component: llamados.append(component) or True\n"
)


def _componentes(importacion: str) -> list[str]:
    script = _ESPIA + importacion + "\nprint('COMPONENTES=' + json.dumps(llamados))\n"
    resultado = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    marca = "COMPONENTES="
    linea = next(
        line for line in resultado.stdout.splitlines() if line.startswith(marca)
    )
    import json

    return list(json.loads(linea[len(marca) :]))


def test_el_proceso_de_la_api_se_inicializa_como_api() -> None:
    assert _componentes("import main") == ["api"]


def test_importar_las_tasks_no_inicializa_observabilidad() -> None:
    """Importar tasks es lo que hace la API sin querer; no es arrancar Celery."""
    assert _componentes("import core.celery_app") == []


def test_el_worker_y_beat_se_inicializan_como_worker() -> None:
    """La guarda sigue viva: el proceso de Celery SI se etiqueta `worker`."""
    componentes = _componentes(
        "import core.celery_app as c\n"
        "c._start_worker_process()\n"
        "c._start_worker_process()\n"
    )

    assert componentes == ["worker", "worker"]


def test_el_arranque_de_celery_sigue_abortando_con_settings_de_respaldo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regla 21: la guarda de configuracion sobrevive a la indireccion nueva."""
    monkeypatch.setattr(
        celery_app, "SETTINGS_BOOT_ERROR", "SECRET_KEY parece un placeholder"
    )

    with pytest.raises(SystemExit) as excinfo:
        celery_app._start_worker_process()

    assert "SECRET_KEY parece un placeholder" in str(excinfo.value)
