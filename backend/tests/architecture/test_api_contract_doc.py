"""docs/API_CONTRACT.md tiene que coincidir con el esquema real de la API.

El documento se genera con scripts/gen_api_contract.py desde app.openapi();
este test es la guarda de CI para que no derive: compara el cuerpo commiteado
(todo menos la linea de pie con fecha y commit) contra lo que el script
generaria hoy.

En el contenedor local solo esta montado backend/, asi que docs/ no existe y
el test se salta. En CI (variable CI definida) no se salta nunca: si el
archivo no se encuentra, falla. API_CONTRACT_DOC permite apuntar a otra copia
del documento (por ejemplo, una copiada al contenedor para verificar).
"""

import os
from pathlib import Path

import pytest

from main import app
from scripts.gen_api_contract import FOOTER_PREFIX, render_contract, split_footer

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOC = REPO_ROOT / "docs" / "API_CONTRACT.md"
REGENERATE = (
    "Regenerar desde la raiz del repo:\n"
    "  MSYS_NO_PATHCONV=1 docker compose exec -T backend "
    "python scripts/gen_api_contract.py --stdout "
    "--commit $(git rev-parse --short HEAD) > docs/API_CONTRACT.md\n"
    "(o, con deps en el host, desde backend/: "
    "uv run python scripts/gen_api_contract.py)"
)


def _contract_doc() -> Path:
    override = os.environ.get("API_CONTRACT_DOC")
    if override:
        return Path(override)
    # Sin docs/ es el contenedor (solo backend/ montado). En CI el repo entero
    # esta en disco, asi que ahi no se tolera la ausencia.
    if not DEFAULT_DOC.parent.is_dir() and not os.environ.get("CI"):
        pytest.skip(
            f"{DEFAULT_DOC.parent} no es alcanzable (contenedor con solo "
            "backend/ montado); definir API_CONTRACT_DOC para verificar."
        )
    return DEFAULT_DOC


def test_api_contract_doc_matches_openapi() -> None:
    doc = _contract_doc()
    assert doc.is_file(), f"No existe {doc}.\n{REGENERATE}"

    body, footer = split_footer(doc.read_text(encoding="utf-8"))
    assert footer is not None, (
        f"{doc} no termina con la linea de pie '{FOOTER_PREFIX}...'.\n{REGENERATE}"
    )
    assert body == render_contract(app.openapi()), (
        f"{doc} no coincide con app.openapi(): la API cambio y el contrato "
        f"no se regenero (diff: gen_api_contract.py --check).\n{REGENERATE}"
    )
