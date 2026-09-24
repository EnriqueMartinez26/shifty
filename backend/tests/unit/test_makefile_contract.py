"""Contrato del Makefile: sus atajos corren con las dependencias que existen.

Defecto real (2026-09-17, C-11): `make test` ejecutaba
`docker compose exec backend pytest` y `make shell`, `... ipython`, pero la
imagen se construye con `uv sync --frozen --no-dev` (backend/Dockerfile) y
tanto `pytest` como `ipython` viven en el grupo `dev` de pyproject.toml.
Sintoma: `exec: "pytest": executable file not found in $PATH`. El atajo que
CLAUDE.md §4 manda usar para replicar CI no corria.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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
        assert not corre_en_un_contenedor(comando), (
            f"`make test` corre pytest en un contenedor, que no tiene tests/: {comando!r}"
        )


# `exec` o `run` de docker/compose, con opciones en el medio. `uv run` no cuenta.
_EN_CONTENEDOR = re.compile(
    r"\bdocker(?:-compose|\s+compose)?\b[^;&|]*?\s(?:exec|run)\s"
)


def corre_en_un_contenedor(comando: str) -> bool:
    return _EN_CONTENEDOR.search(comando) is not None


@pytest.mark.parametrize(
    ("comando", "esperado"),
    [
        ("docker compose exec backend pytest", True),
        ("docker compose run --rm backend uv run pytest", True),
        ("docker-compose -f x.yml run backend pytest", True),
        ("docker run --rm shifty-backend pytest", True),
        ("cd backend && uv run --frozen --group dev pytest", False),
    ],
)
def test_el_contrato_distingue_exec_y_run_de_un_contenedor(
    comando: str, esperado: bool
) -> None:
    assert corre_en_un_contenedor(comando) is esperado


def test_makemigrations_trae_la_revision_al_host() -> None:
    """Sin el montaje, la revision que genera alembic en el contenedor solo
    existiria ahi y se perderia al recrearlo."""
    receta = " ".join(_receta("makemigrations"))
    assert "alembic revision" in receta, receta
    assert "docker compose cp" in receta, (
        f"`make makemigrations` deja la revision dentro del contenedor: {receta!r}"
    )


def test_makemigrations_no_pisa_una_migracion_del_host() -> None:
    """Una migracion editada en el host despues del build no se reemplaza."""
    receta = "\n".join(_receta("makemigrations"))
    assert re.search(r'\[ -e "[^"]*\$\$f" \] \|\| docker compose cp ', receta), (
        f"`make makemigrations` copia sin mirar si el host ya tiene el archivo: {receta!r}"
    )


def test_todo_objetivo_del_makefile_es_phony() -> None:
    texto = MAKEFILE.read_text(encoding="utf-8")
    phony = re.search(r"^\.PHONY:(.*)$", texto, re.MULTILINE)
    assert phony, "el Makefile no declara .PHONY"
    objetivos = set(re.findall(r"^([a-z][\w-]*):(?!=)", texto, re.MULTILINE))
    faltan = objetivos - set(phony.group(1).split())
    assert not faltan, f"objetivos sin .PHONY (un archivo homonimo los apaga): {faltan}"


# --- makemigrations no resucita revisiones descartadas (2026-09-24) ------------
#
# Sintoma: la receta copiaba al host TODO /app/alembic/versions del contenedor
# que el host no tuviera. Una revision generada, rechazada y borrada en el host
# seguia viva en el contenedor: la siguiente corrida la traia de vuelta y ademas
# la usaba como head de la nueva. Se prueba la receta REAL contra un `docker`
# falso cuyo "contenedor" es un directorio.

_DOCKER_FALSO = """#!/bin/sh
echo "$*" >> "$LLAMADAS"
[ "$1" = compose ] || exit 90
shift
case "$1" in
  exec)
    shift
    [ "$1" = -T ] && shift
    shift
    case "$1" in
      ls) ls -1 "$CONTENEDOR" ;;
      alembic) echo "# nueva" > "$CONTENEDOR/$NUEVA" ;;
      *) exit 91 ;;
    esac ;;
  cp)
    origen="${2#backend:/app/alembic/versions}"
    cp -r "$CONTENEDOR$origen" "$3" ;;
  *) exit 92 ;;
esac
"""


def _lineas_logicas(receta: list[str]) -> list[str]:
    """Cada linea de receta la corre make en su propio shell; `\\` las une."""
    lineas: list[str] = []
    actual = ""
    for linea in receta:
        actual += linea + "\n"
        if not linea.endswith("\\"):
            lineas.append(actual)
            actual = ""
    if actual:
        lineas.append(actual)
    return lineas


def _correr_makemigrations(
    tmp_path: Path, en_el_host: dict[str, str], en_el_contenedor: dict[str, str]
) -> tuple[int, list[str]]:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("hace falta un sh para correr la receta")
    host = tmp_path / "repo" / "backend" / "alembic" / "versions"
    contenedor = tmp_path / "contenedor"
    bin_dir = tmp_path / "bin"
    for directorio, archivos in ((host, en_el_host), (contenedor, en_el_contenedor)):
        directorio.mkdir(parents=True)
        for nombre, contenido in archivos.items():
            (directorio / nombre).write_text(contenido, encoding="utf-8")
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(_DOCKER_FALSO, encoding="utf-8", newline="\n")
    docker.chmod(0o755)
    llamadas = tmp_path / "llamadas.txt"
    llamadas.touch()
    entorno = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "CONTENEDOR": contenedor.as_posix(),
        "NUEVA": "c3_nueva.py",
        "LLAMADAS": llamadas.as_posix(),
    }
    codigo = 0
    for linea in _lineas_logicas(_receta("makemigrations")):
        comando = linea.lstrip("@-").replace("$(name)", "prueba").replace("$$", "$")
        codigo = subprocess.run(
            [sh, "-c", comando], cwd=tmp_path / "repo", env=entorno, check=False
        ).returncode
        if codigo:
            break
    return codigo, llamadas.read_text(encoding="utf-8").splitlines()


def test_makemigrations_trae_solo_la_revision_nueva(tmp_path: Path) -> None:
    codigo, _ = _correr_makemigrations(
        tmp_path,
        en_el_host={"a1_base.py": "# editada en el host"},
        en_el_contenedor={"a1_base.py": "# la de la imagen"},
    )
    assert codigo == 0
    versiones = tmp_path / "repo" / "backend" / "alembic" / "versions"
    assert sorted(p.name for p in versiones.iterdir()) == ["a1_base.py", "c3_nueva.py"]
    assert (versiones / "a1_base.py").read_text(encoding="utf-8") == (
        "# editada en el host"
    ), "makemigrations piso una migracion del host"
    assert not (tmp_path / "repo" / ".makemigrations-tmp").exists()


def test_makemigrations_no_resucita_una_revision_descartada(tmp_path: Path) -> None:
    codigo, llamadas = _correr_makemigrations(
        tmp_path,
        en_el_host={"a1_base.py": "# base"},
        en_el_contenedor={"a1_base.py": "# base", "b2_rechazada.py": "# rechazada"},
    )
    versiones = tmp_path / "repo" / "backend" / "alembic" / "versions"
    assert not (versiones / "b2_rechazada.py").exists(), (
        "makemigrations trajo de vuelta una revision borrada en el host"
    )
    # Tampoco se genera la nueva: seria hija de la rechazada (su head).
    assert codigo != 0, "makemigrations siguio con una revision descartada como head"
    assert not any("alembic revision" in llamada for llamada in llamadas), llamadas


def test_make_dev_quita_los_contenedores_de_servicios_que_ya_no_existen() -> None:
    """F0-15 (2026-09-24): el servicio `redis` se partio en redis_cache y
    redis_state. El contenedor viejo queda huerfano, sigue publicando
    127.0.0.1:6379 y redis_state no puede levantar ("port is already
    allocated"). `--remove-orphans` lo quita en el mismo `up`."""
    receta = _receta("dev")
    assert receta, "El Makefile no define el objetivo dev"
    assert any("up" in c and "--remove-orphans" in c for c in receta), receta
