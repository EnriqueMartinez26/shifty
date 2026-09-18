"""Los tres procesos arrancan con el entorno YA resuelto en build time.

Defecto real (2026-09-17, C-16): la imagen se construye con
`uv sync --frozen --no-dev` (backend/Dockerfile) pero el `CMD` y los dos
`command:` de Celery arrancaban con `uv run`, que reconcilia el proyecto
antes de ejecutar: lee pyproject.toml/uv.lock desde /app -- que en
desarrollo es un bind-mount del host -- y puede escribir ahi y en
/app/.venv como uid 10001 sobre un directorio del uid del host. Sin
`--no-dev` ademas apunta a un entorno distinto del construido. Es el mismo
modo de fallo que CLAUDE.md §1 ya documenta ("un restart deja el contenedor
no-root en crash-loop"). El PATH de la imagen ya apunta al venv, asi que la
indireccion no aporta nada.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"

SERVICIOS_DEL_BACKEND = ("backend", "celery_worker", "celery_beat")


def test_el_path_de_la_imagen_apunta_al_venv_construido() -> None:
    # Es lo que vuelve innecesaria la indireccion de `uv run`.
    contenido = DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENV PATH="/app/.venv/bin:$PATH"' in contenido
    assert "--no-dev" in contenido


def test_el_cmd_de_la_imagen_no_pasa_por_uv_run() -> None:
    for linea in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if not linea.startswith("CMD"):
            continue
        assert '"uv"' not in linea and "uv run" not in linea, (
            f"el CMD vuelve a resolver el entorno en cada arranque: {linea!r}"
        )


def test_los_comandos_de_celery_no_pasan_por_uv_run() -> None:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for nombre in SERVICIOS_DEL_BACKEND:
        comando = str((data["services"][nombre] or {}).get("command", ""))
        assert not comando.strip().startswith("uv run"), (
            f"{nombre} arranca con `uv run`, que reconcilia /app en runtime: "
            f"{comando!r}"
        )
