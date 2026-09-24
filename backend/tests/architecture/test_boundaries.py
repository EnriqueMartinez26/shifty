"""Limites entre capas del backend, verificables y no solo documentados.

2026-09-17 · C-12. Sintoma: el unico test de arquitectura recorria dos rutas
literales (`appointments/service.py` y `appointments/domain_service.py`) y no
afirmaba nada sobre "commit solo en service" (CLAUDE.md §2). Un
`domain_service.py` nuevo en otro modulo, o un `db.commit()` nuevo en un
router o repository, pasaban la suite sin ruido.
"""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"

FORBIDDEN_FRAMEWORK_IMPORTS = {
    "fastapi",
    "flask",
    "django",
    "starlette",
    "pydantic",
    "tkinter",
    "react",
    "streamlit",
}

# Deuda declarada de "commit solo en service" (CLAUDE.md §2): TECHO de
# llamadas `.commit(` por archivo al 2026-09-17. La deuda solo puede bajar: el
# test falla si un archivo commitea MAS que su numero o si aparece un router o
# repository con commits fuera de esta lista; si commitea menos, pasa. Al
# migrar commits al service, bajar el numero (o borrar la entrada si llega a
# 0) es deseable para que la deuda no vuelva a crecer, pero no obligatorio:
# varias ramas migran en paralelo y la igualdad estricta rompia al integrarlas
# aunque la deuda hubiera bajado. CLAUDE.md §2 nombraba solo cuatro de estos
# archivos (public_api, payments, stores, superadmin) cuando el codigo tenia
# once; desde 2026-09-19 no los lista y remite a esta tabla.
COMMITS_DECLARADOS_FUERA_DE_SERVICE: dict[str, int] = {
    "modules/appointments/repository.py": 2,
    "modules/ledger/router.py": 2,
    "modules/notifications/router.py": 2,
    "modules/payments/router.py": 5,
    "modules/promotions/router.py": 3,
    "modules/services/repository.py": 3,
    "modules/staff/repository.py": 4,
    "modules/stores/router.py": 3,
    "modules/superadmin/repository.py": 11,
    "modules/users/repository.py": 3,
}


def _module_imports(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    return imports


def _commit_calls(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    )


def _relative(path: Path) -> str:
    return path.relative_to(BACKEND_ROOT).as_posix()


def test_domain_and_application_layers_do_not_import_ui_frameworks() -> None:
    domain_services = sorted(MODULES_ROOT.glob("*/domain_service.py"))
    assert domain_services, "no se encontro ningun modules/*/domain_service.py"
    layer_files = [MODULES_ROOT / "appointments/service.py", *domain_services]

    for path in layer_files:
        imports = _module_imports(path)
        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_FRAMEWORK_IMPORTS
            for imported in imports
        ), f"{path} imports a UI/framework dependency: {sorted(imports)}"


def test_domain_services_no_importan_sqlalchemy_ni_la_sesion() -> None:
    # Libre de framework de verdad: tampoco el ORM ni core.database.
    for path in sorted(MODULES_ROOT.glob("*/domain_service.py")):
        imports = _module_imports(path)
        prohibidos = sorted(
            imported
            for imported in imports
            if imported.split(".", 1)[0] == "sqlalchemy"
            or imported.startswith("core.database")
        )
        assert not prohibidos, f"{_relative(path)} importa persistencia: {prohibidos}"


def _violaciones_de_la_deuda(
    reales: dict[str, int], techo: dict[str, int]
) -> list[str]:
    """Archivos que superan su techo o que commitean sin estar en la lista."""
    violaciones: list[str] = []
    for ruta, actuales in sorted(reales.items()):
        if not actuales:
            continue
        if ruta not in techo:
            violaciones.append(f"{ruta}: {actuales} commits y no esta en la deuda")
        elif actuales > techo[ruta]:
            violaciones.append(
                f"{ruta}: {actuales} commits, la deuda declarada es {techo[ruta]}"
            )
    return violaciones


def test_commit_solo_en_service() -> None:
    reales = {
        _relative(path): _commit_calls(path)
        for path in sorted(MODULES_ROOT.rglob("*.py"))
        if path.name in {"router.py", "repository.py"}
    }

    violaciones = _violaciones_de_la_deuda(reales, COMMITS_DECLARADOS_FUERA_DE_SERVICE)
    assert not violaciones, (
        "commit nuevo fuera de service (CLAUDE.md §2: la transaccion es del "
        f"service; migra el commit, no extiendas la excepcion): {violaciones}"
    )


def test_el_trinquete_es_un_techo() -> None:
    techo = {"modules/a/router.py": 3}

    # Menos commits que el techo: la deuda bajo, pasa (2026-09-18: la igualdad
    # estricta rompia al integrar ramas que migran commits al service).
    assert _violaciones_de_la_deuda({"modules/a/router.py": 1}, techo) == []
    assert _violaciones_de_la_deuda({"modules/a/router.py": 0}, techo) == []
    assert _violaciones_de_la_deuda({}, techo) == []

    # Mas commits que el techo: falla.
    assert _violaciones_de_la_deuda({"modules/a/router.py": 4}, techo)

    # Un archivo que no esta en la lista y commitea: falla.
    assert _violaciones_de_la_deuda({"modules/b/repository.py": 1}, techo)


# Archivos del portal que usan PublicRepository: el router y, desde B1-12,
# el service que se quedo con la reserva y la autogestion.
PORTAL_PUBLICO = ("modules/public_api/router.py", "modules/public_api/service.py")
_NOMBRES_DEL_REPO = {"repo", "_repo"}


def _accesos_privados_al_repo(fuente: str) -> list[str]:
    """``repo._x``, ``self.repo._x`` y ``self._repo._x``, con su linea."""
    encontrados: list[str] = []
    for node in ast.walk(ast.parse(fuente)):
        if not (isinstance(node, ast.Attribute) and node.attr.startswith("_")):
            continue
        dueno = node.value
        if isinstance(dueno, ast.Name) and dueno.id in _NOMBRES_DEL_REPO:
            encontrados.append(f"{dueno.id}.{node.attr} (linea {node.lineno})")
        elif (
            isinstance(dueno, ast.Attribute)
            and dueno.attr in _NOMBRES_DEL_REPO
            and isinstance(dueno.value, ast.Name)
            and dueno.value.id == "self"
        ):
            encontrados.append(f"self.{dueno.attr}.{node.attr} (linea {node.lineno})")
    return sorted(encontrados)


def test_el_portal_publico_no_usa_metodos_privados_del_repositorio() -> None:
    """Audit B1-19 (2026-09-18): la agenda del alta y de la reprogramacion.

    ``client_reschedule_appointment`` llamaba ``repo._staff_has_schedule_for_slot``
    y ``repo._staff_has_overlapping_block`` y repetia a mano el lock y la
    consulta de choque: dos copias de "este profesional puede tomar este
    rango" con reglas que divergieron (B1-05 y B1-07 afectaron a una sola).
    Ahora hay una funcion publica en el repositorio y la relectura bajo lock
    (regla 4) queda de ese lado.

    Desde B1-12 (2026-09-19) la reprogramacion vive en
    ``public_api/service.py`` y usa ``self.repo``: la guarda recorre los dos
    archivos y tambien los accesos por atributo.
    """
    backend_root = Path(__file__).resolve().parents[2]
    privados = {
        ruta: _accesos_privados_al_repo(
            (backend_root / ruta).read_text(encoding="utf-8")
        )
        for ruta in PORTAL_PUBLICO
    }
    assert not any(privados.values()), (
        f"el portal usa metodos privados del repositorio: {privados}"
    )


def test_la_guarda_de_privados_ve_todas_las_formas_de_acceso() -> None:
    """Sin esto, la guarda podria pasar por no mirar donde hay que mirar."""
    fuente = (
        "async def f(self, repo):\n"
        "    await repo._staff_has_x()\n"
        "    await self.repo._staff_has_x()\n"
        "    await self._repo._staff_has_x()\n"
        "    await self.repo.staff_can_take_range()\n"
        "    await self.otro._privado()\n"
    )
    assert _accesos_privados_al_repo(fuente) == [
        "repo._staff_has_x (linea 2)",
        "self._repo._staff_has_x (linea 4)",
        "self.repo._staff_has_x (linea 3)",
    ]
