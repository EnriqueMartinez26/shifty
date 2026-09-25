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

AUD2-POST-08 (2026-09-23): un solo recorrido del arbol que junta todos los
identificadores y despues consulta pertenencia (antes se re-parseaban ~430
archivos por cada nombre). Y ``tests/`` queda afuera a proposito: un nombre que
solo aparece en un test no es una politica aplicada, es un test de una
constante muerta.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
# Codigo vivo: donde una constante de roles tiene que estar cableada.
ARBOLES_VIVOS = ("core", "modules", "infrastructure", "scripts")


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


def _identificadores(archivo: Path, *, roles: Path) -> set[str]:
    """Nombres, atributos e imports de un archivo; en ``roles`` sin sus definiciones."""
    try:
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - archivo generado o roto
        return set()
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Name):
            # La propia asignacion en roles.py no cuenta como uso.
            if archivo == roles and isinstance(nodo.ctx, ast.Store):
                continue
            nombres.add(nodo.id)
        elif isinstance(nodo, ast.Attribute):
            nombres.add(nodo.attr)
        elif isinstance(nodo, ast.alias):
            nombres.add(nodo.name)
    return nombres


def _usados_en_codigo_vivo(raiz: Path) -> set[str]:
    """UN recorrido de ``ARBOLES_VIVOS`` y ``main.py``; ``tests/`` no cuenta."""
    roles = raiz / "core" / "roles.py"
    usados: set[str] = set()
    for carpeta in ARBOLES_VIVOS:
        for archivo in (raiz / carpeta).rglob("*.py"):
            usados |= _identificadores(archivo, roles=roles)
    principal = raiz / "main.py"
    if principal.exists():
        usados |= _identificadores(principal, roles=roles)
    return usados


def _huerfanos(raiz: Path) -> list[str]:
    roles = raiz / "core" / "roles.py"
    usados = _usados_en_codigo_vivo(raiz)
    return sorted(
        nombre
        for nombre in _nombres_publicos(roles.read_text(encoding="utf-8"))
        if nombre not in usados
    )


def test_ningun_nombre_publico_de_roles_queda_sin_aplicar() -> None:
    huerfanos = _huerfanos(BACKEND)
    assert not huerfanos, (
        f"core/roles.py declara {huerfanos} y nadie los usa: es una politica de "
        "permisos que el codigo vivo no aplica, en el archivo que CLAUDE.md "
        "senala como fuente de la matriz de roles. O se cablean, o se borran."
    )


def test_un_uso_solo_en_tests_no_cuenta_como_politica_aplicada(
    tmp_path: Path,
) -> None:
    """La guarda misma, sobre un arbol de juguete: ``tests/`` no la satisface."""
    (tmp_path / "core").mkdir()
    (tmp_path / "modules").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "core" / "roles.py").write_text(
        "CABLEADA = {'a'}\nSOLO_EN_TESTS = {'b'}\n"
        "def usada_adentro() -> set[str]:\n    return CABLEADA\n",
        encoding="utf-8",
    )
    (tmp_path / "modules" / "router.py").write_text(
        "from core.roles import usada_adentro\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_roles.py").write_text(
        "from core.roles import SOLO_EN_TESTS\n", encoding="utf-8"
    )

    assert _huerfanos(tmp_path) == ["SOLO_EN_TESTS"]
