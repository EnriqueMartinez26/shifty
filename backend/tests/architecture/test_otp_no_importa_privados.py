"""``otp`` usa la API publica de ``notifications``, importada arriba.

B4-12 (2026-09-18): ``modules/otp/service.py`` hacia
``from modules.notifications.tasks import _send_email`` DENTRO de la funcion
que despacha el codigo: un modulo consumia el helper privado de otro, con un
import diferido que escondia la dependencia. Ahora ``notifications`` expone
``send_email`` y ``otp`` lo importa a nivel de modulo. La respuesta neutra
ante fallo de envio sigue en ``otp`` (``tests/integration/test_otp_por_email``).
"""

from __future__ import annotations

import ast
from pathlib import Path

OTP_SERVICE = Path(__file__).resolve().parents[2] / "modules" / "otp" / "service.py"


def _imports(tree: ast.AST) -> list[tuple[ast.ImportFrom, bool]]:
    """(import, esta_dentro_de_una_funcion) para cada ``from ... import``."""
    encontrados: list[tuple[ast.ImportFrom, bool]] = []

    def visitar(nodo: ast.AST, en_funcion: bool) -> None:
        for hijo in ast.iter_child_nodes(nodo):
            dentro = en_funcion or isinstance(
                hijo, (ast.FunctionDef, ast.AsyncFunctionDef)
            )
            if isinstance(hijo, ast.ImportFrom):
                encontrados.append((hijo, en_funcion))
            visitar(hijo, dentro)

    visitar(tree, False)
    return encontrados


def test_otp_no_importa_privados_de_notifications_ni_dentro_de_funciones() -> None:
    tree = ast.parse(OTP_SERVICE.read_text(encoding="utf-8"), filename=str(OTP_SERVICE))
    desde_notifications = [
        (nodo, en_funcion)
        for nodo, en_funcion in _imports(tree)
        if (nodo.module or "").startswith("modules.notifications")
    ]
    assert desde_notifications, "otp debe despachar el codigo por notifications"
    for nodo, en_funcion in desde_notifications:
        nombres = [alias.name for alias in nodo.names]
        assert not en_funcion, f"import diferido en la linea {nodo.lineno}: {nombres}"
        privados = [n for n in nombres if n.startswith("_")]
        assert not privados, f"otp importa privados de notifications: {privados}"
