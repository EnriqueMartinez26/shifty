"""docs/API_CONTRACT.md tiene que coincidir con el esquema real de la API.

El documento se genera con scripts/gen_api_contract.py desde app.openapi();
este test es la guarda de CI para que no derive: compara el cuerpo commiteado
(todo menos la linea de pie con fecha y commit) contra lo que el script
generaria hoy.

Un contenedor corre la imagen, que no trae docs/, asi que ahi el test se
salta. En CI (variable CI definida) no se salta nunca: si el
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
    "Regenerar desde el working tree (nunca con `exec`: el contenedor corre "
    "la imagen del ultimo build).\n"
    "  Con uv, desde backend/: uv run python scripts/gen_api_contract.py\n"
    "  Sin uv, desde la raiz: MSYS_NO_PATHCONV=1 docker compose run --rm "
    "--no-deps -v ./backend:/src -w /src backend /app/.venv/bin/python "
    "scripts/gen_api_contract.py --stdout "
    "--commit $(git rev-parse --short HEAD) > docs/API_CONTRACT.md"
)


def _contract_doc() -> Path:
    override = os.environ.get("API_CONTRACT_DOC")
    if override:
        return Path(override)
    # Sin docs/ es un contenedor (corre la imagen). En CI el repo entero
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


def test_operation_ids_son_unicos() -> None:
    """Cada operacion del esquema tiene su propio operationId.

    Un generador de cliente (TypeScript, SDK) usa el operationId como nombre
    de funcion: dos iguales se pisan. Paso con el GET y el HEAD de
    /stores/media/{media_id} registrados con un solo api_route (2026-09-25).
    """
    vistos: dict[str, str] = {}
    repetidos: list[str] = []
    for path, item in app.openapi()["paths"].items():
        for method, operation in item.items():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            op_id = operation["operationId"]
            donde = f"{method.upper()} {path}"
            if op_id in vistos:
                repetidos.append(f"{op_id}: {vistos[op_id]} y {donde}")
            vistos[op_id] = donde
    assert not repetidos, "operationId repetidos:\n" + "\n".join(repetidos)
