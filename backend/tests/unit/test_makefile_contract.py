"""Contrato del Makefile: sus atajos corren con las dependencias que existen.

Defecto real (2026-09-17, C-11): `make test` ejecutaba
`docker compose exec backend pytest` y `make shell`, `... ipython`, pero la
imagen se construye con `uv sync --frozen --no-dev` (backend/Dockerfile) y
tanto `pytest` como `ipython` viven en el grupo `dev` de pyproject.toml.
Sintoma: `exec: "pytest": executable file not found in $PATH`. El atajo que
CLAUDE.md §4 manda usar para replicar CI no corria.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"

# Herramientas que solo existen en el grupo `dev`, excluido de la imagen.
SOLO_EN_DEV = ("pytest", "ipython")


def _receta(objetivo: str) -> list[str]:
    lineas: list[str] = []
    dentro = False
    for linea in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if linea.startswith(f"{objetivo}:"):
            dentro = True
            continue
        if dentro:
            if linea.startswith("\t"):
                lineas.append(linea.strip())
                continue
            break
    return lineas


def test_la_imagen_sigue_construyendose_sin_el_grupo_dev() -> None:
    # Si esto cambia, el resto del contrato deja de tener sentido.
    assert "--no-dev" in DOCKERFILE.read_text(encoding="utf-8")


def test_los_atajos_de_dev_piden_el_grupo_dev() -> None:
    for objetivo in ("test", "shell"):
        receta = _receta(objetivo)
        assert receta, f"El Makefile no define el objetivo {objetivo}"
        for comando in receta:
            if not any(herramienta in comando for herramienta in SOLO_EN_DEV):
                continue
            assert "--group dev" in comando, (
                f"`make {objetivo}` invoca una herramienta del grupo dev sin "
                f"pedirlo, y la imagen se construye con --no-dev: {comando!r}"
            )
            # Sin --frozen, `uv run` puede re-resolver y reescribir uv.lock.
            assert "uv run --frozen" in comando, (
                f"`make {objetivo}` corre `uv run` sin --frozen y puede reescribir "
                f"uv.lock: {comando!r}"
            )


# 2026-09-24: el codigo sale de la imagen, no de un bind mount del host
# (tests/unit/test_compose_contract.py). El volumen anonimo /app/.venv que
# obligaba a `--renew-anon-volumes` (C-20, 2026-09-18) ya no existe: esa
# proteccion vive ahora en test_los_servicios_de_la_app_no_montan_codigo_del_host.
# Lo que dependia del montaje son los atajos que leen o escriben archivos del
# arbol del host desde el contenedor.


def test_make_test_no_corre_dentro_del_contenedor() -> None:
    """La imagen no trae tests/ (backend/.dockerignore): sin el montaje, pytest
    dentro del contenedor no encuentra nada que correr."""
    ignorados = (REPO_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
    assert "tests" in ignorados.split(), "la imagen volvio a traer tests/"
    receta = _receta("test")
    assert receta, "El Makefile no define el objetivo test"
    for comando in receta:
        assert "exec backend" not in comando, (
            f"`make test` corre pytest en el contenedor, que no tiene tests/: {comando!r}"
        )


def test_makemigrations_trae_la_revision_al_host() -> None:
    """Sin el montaje, la revision que genera alembic en el contenedor solo
    existiria ahi y se perderia al recrearlo."""
    receta = " ".join(_receta("makemigrations"))
    assert "alembic revision" in receta, receta
    assert "docker compose cp" in receta, (
        f"`make makemigrations` deja la revision dentro del contenedor: {receta!r}"
    )
