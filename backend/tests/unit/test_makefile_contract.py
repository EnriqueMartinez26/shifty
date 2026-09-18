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
            # Sin --frozen, `uv run` puede re-resolver y reescribir uv.lock,
            # que en el contenedor de desarrollo es el del host (bind-mount).
            assert "uv run --frozen" in comando, (
                f"`make {objetivo}` corre `uv run` sin --frozen y puede reescribir "
                f"uv.lock en el bind-mount: {comando!r}"
            )
