"""Contrato de `.github/dependabot.yml`: los tres ecosistemas del repo.

C-23 (2026-09-19): el repo no tenia actualizaciones automaticas de
dependencias. Sin esto, una dependencia con CVE se entera cuando alguien
mira; `npm audit` solo corre sobre el front y no abre PRs.

Este test no prueba que Dependabot funcione (eso pasa en GitHub): prueba que
el archivo parsea y que sigue cubriendo backend, frontend y acciones de CI
con actualizaciones agrupadas y acotadas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

# El de Python admite "uv" (lee backend/uv.lock) o "pip" como alternativa
# documentada en el propio archivo.
ECOSISTEMAS_ESPERADOS = {
    ("uv", "/backend"),
    ("pip", "/backend"),
    ("npm", "/frontend"),
    ("github-actions", "/"),
}


def _config() -> dict[str, Any]:
    data = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_el_archivo_parsea_y_declara_la_version_2() -> None:
    assert DEPENDABOT.exists(), "falta .github/dependabot.yml"
    assert _config()["version"] == 2


def test_cubre_backend_frontend_y_acciones() -> None:
    declarados = {
        (str(u["package-ecosystem"]), str(u["directory"])) for u in _config()["updates"]
    }
    assert declarados <= ECOSISTEMAS_ESPERADOS, (
        f"ecosistema o directorio inesperado: {declarados - ECOSISTEMAS_ESPERADOS}"
    )

    backend = {e for e in declarados if e[1] == "/backend"}
    assert backend, "falta el backend (uv o pip sobre /backend)"
    assert ("npm", "/frontend") in declarados, "falta el frontend"
    assert ("github-actions", "/") in declarados, "faltan las acciones de CI"


def test_cada_ecosistema_es_semanal_agrupado_y_acotado() -> None:
    for update in _config()["updates"]:
        nombre = update["package-ecosystem"]
        assert update["schedule"]["interval"] == "weekly", nombre
        limite = update["open-pull-requests-limit"]
        assert 1 <= limite <= 5, f"{nombre}: {limite} PRs abiertos es demasiado"
        grupos = update["groups"]
        assert grupos, f"{nombre} no agrupa: seran decenas de PRs"
        for grupo in grupos.values():
            assert set(grupo["update-types"]) == {"minor", "patch"}, (
                f"{nombre}: el grupo solo junta menores y parches; una mayor "
                "va en su propio PR"
            )


def test_el_archivo_dice_que_las_alertas_se_activan_en_github() -> None:
    # Es el paso que Dependabot NO puede configurar desde el repo y que tiene
    # que hacer el dueno.
    texto = DEPENDABOT.read_text(encoding="utf-8")
    assert "Dependabot alerts" in texto and "configuracion del repositorio" in texto
