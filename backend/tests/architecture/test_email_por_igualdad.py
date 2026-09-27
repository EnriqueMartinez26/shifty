"""El email se busca por igualdad sobre la columna normalizada (F1-12, R7-01).

2026-09-24, plan de rendimiento. Sintoma: el login, el olvido de clave, el
alta y la edicion de staff y el alta de admins por superadmin buscaban con
``func.lower(User.email) == x``. ``lower`` no es leakproof: bajo RLS no puede
ser condicion de indice y cada login recorria ``users`` entera. La columna ya
esta normalizada (``CHECK ck_users_email_lower``), asi que la busqueda es
``User.email == normalize_email(x)`` y usa ``ix_users_email``.

Guarda estatica: ninguna consulta de ``modules/`` vuelve a aplicar ``lower`` a
la columna de email. El plan real lo prueba
``tests/postgres/test_pg_email_por_igualdad.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _lower_sobre_email(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lineas = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "lower"
            and node.args
        ):
            continue
        argumento = node.args[0]
        if isinstance(argumento, ast.Attribute) and argumento.attr == "email":
            lineas.append(node.lineno)
    return lineas


def test_ninguna_consulta_aplica_lower_a_la_columna_de_email() -> None:
    hallazgos = {
        str(path.relative_to(BACKEND_ROOT)): lineas
        for path in sorted((BACKEND_ROOT / "modules").rglob("*.py"))
        if (lineas := _lower_sobre_email(path))
    }
    assert not hallazgos, (
        "func.lower(<modelo>.email) no usa indice bajo RLS; comparar la columna "
        f"con normalize_email(x): {hallazgos}"
    )
