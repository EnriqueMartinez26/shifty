"""Contrato estatico de los scripts de operacion del host (scripts/*.sh).

2026-09-24 (Fase 0). Corren en el VPS como root o como el usuario del deploy:
tienen que parsear, ser estrictos (`set -euo pipefail`), no escalar con sudo
ni tocar docker.sock (plan §7, decision 25) y llegar al servidor con LF.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from tests.unit.host_falso import BASH, REPO_ROOT, SCRIPTS, requiere_bash

SCRIPTS_DE_HOST = sorted(p.name for p in SCRIPTS.glob("*.sh"))


def test_hay_scripts_de_host() -> None:
    assert SCRIPTS_DE_HOST, "no hay scripts/*.sh"


@requiere_bash
@pytest.mark.parametrize("script", [*SCRIPTS_DE_HOST, "lib/common.sh"])
def test_el_script_parsea_con_bash_n(script: str) -> None:
    assert BASH is not None
    resultado = subprocess.run(
        [BASH, "-n", str(SCRIPTS / script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize("script", SCRIPTS_DE_HOST)
def test_el_script_es_estricto_y_no_escala_privilegios(script: str) -> None:
    texto = (SCRIPTS / script).read_text(encoding="utf-8")
    assert texto.startswith("#!/usr/bin/env bash\n"), script
    assert "\r" not in texto, f"{script} tiene CRLF: cron y bash lo rompen"
    assert re.search(r"^set -[E]?euo pipefail$", texto, re.MULTILINE), script
    # Nada de sudo adentro ni de montar el socket de docker (plan §7, 25).
    sin_comentarios = "\n".join(
        linea for linea in texto.splitlines() if not linea.lstrip().startswith("#")
    )
    assert not re.search(r"\bsudo\b", sin_comentarios), script
    assert "docker.sock" not in sin_comentarios, script


def test_los_archivos_del_host_quedan_en_lf_para_git() -> None:
    """autocrlf en Windows dejaria CRLF en un clon de Windows; en el VPS un
    cron.d o un unit con CRLF no se lee. .gitattributes lo fija."""
    atributos = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"^\*\.sh text eol=lf$", atributos, re.MULTILINE)
    assert re.search(r"^deploy/\*\* text eol=lf$", atributos, re.MULTILINE)
