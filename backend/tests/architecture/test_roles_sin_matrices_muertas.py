"""``core/roles.py`` no declara politicas de permisos que nadie aplica.

AUD2-B3-06, 2026-09-20. Sintoma: ``FINANCIAL_OPERATORS`` y ``FINANCIAL_ADMINS``
existian en ``core/roles.py`` con CERO usos --ni en ``modules/``, ni en
``core/``, ni en ``main.py``, ni en ``scripts/``, ni en ``tests/``, ni dentro
del propio archivo--. Quien decide de verdad quien opera cobros y fiado son
``_require_payment_manager`` / ``_require_payment_admin``
(``modules/payments/router.py``) y ``_require_financial_access``
(``modules/ledger/router.py``), que comparan el enum crudo.

Las dos politicas no coincidian: ``FINANCIAL_OPERATORS`` incluia
``ROLE_RECEPTIONIST`` y las funciones vivas lo excluyen. Leyendo el archivo que
``CLAUDE.md`` senala como fuente de la matriz de roles se concluia que una
recepcionista puede cobrar y ver deudas; en produccion recibe 403. ``CLAUDE.md``
§5 ya declara que ``docs/ROLE_MATRIX.md`` derivo contra el codigo y manda
verificar EN el codigo: el problema era que la deriva estaba adentro del codigo,
en el archivo al que esa instruccion manda mirar.

Esta guarda es del mismo espiritu que ``test_model_registry``: un nombre
publico de ``core/roles.py`` que nadie usa es una politica que nadie aplica.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROLES = BACKEND / "core" / "roles.py"
ARBOLES = ("core", "modules", "infrastructure", "scripts", "tests")


def _nombres_publicos(fuente: str) -> set[str]:
    """Constantes y funciones de nivel de modulo que no empiezan con ``_``."""
    arbol = ast.parse(fuente)
    nombres: set[str] = set()
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not nodo.name.startswith("_"):
                nombres.add(nodo.name)
        elif isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name) and not destino.id.startswith("_"):
                    nombres.add(destino.id)
    return nombres


def _usos(nombre: str) -> int:
    """Veces que el nombre aparece como identificador, sin contar su definicion."""
    total = 0
    for carpeta in ARBOLES:
        for archivo in (BACKEND / carpeta).rglob("*.py"):
            try:
                arbol = ast.parse(archivo.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - archivo generado o roto
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Name) and nodo.id == nombre:
                    # La propia asignacion en roles.py no cuenta como uso.
                    if archivo == ROLES and isinstance(nodo.ctx, ast.Store):
                        continue
                    total += 1
                elif isinstance(nodo, ast.Attribute) and nodo.attr == nombre:
                    total += 1
                elif isinstance(nodo, ast.alias) and nodo.name == nombre:
                    total += 1
    for archivo in (BACKEND / "main.py",):
        if nombre in archivo.read_text(encoding="utf-8"):
            total += 1
    return total


def test_ningun_nombre_publico_de_roles_queda_sin_aplicar() -> None:
    huerfanos = sorted(
        nombre
        for nombre in _nombres_publicos(ROLES.read_text(encoding="utf-8"))
        if _usos(nombre) == 0
    )
    assert not huerfanos, (
        f"core/roles.py declara {huerfanos} y nadie los usa: es una politica de "
        "permisos que el codigo vivo no aplica, en el archivo que CLAUDE.md "
        "senala como fuente de la matriz de roles. O se cablean, o se borran."
    )
