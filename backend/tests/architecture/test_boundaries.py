from __future__ import annotations

import ast
from pathlib import Path


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


def test_domain_and_application_layers_do_not_import_ui_frameworks() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    layer_files = [
        backend_root / "modules/appointments/service.py",
        backend_root / "modules/appointments/domain_service.py",
    ]

    for path in layer_files:
        imports = _module_imports(path)
        assert not any(
            imported.split(".", 1)[0] in FORBIDDEN_FRAMEWORK_IMPORTS
            for imported in imports
        ), f"{path} imports a UI/framework dependency: {sorted(imports)}"


def test_el_router_publico_no_usa_metodos_privados_del_repositorio() -> None:
    """Audit B1-19 (2026-09-18): la agenda del alta y de la reprogramacion.

    ``client_reschedule_appointment`` llamaba ``repo._staff_has_schedule_for_slot``
    y ``repo._staff_has_overlapping_block`` y repetia a mano el lock y la
    consulta de choque: dos copias de "este profesional puede tomar este
    rango" con reglas que divergieron (B1-05 y B1-07 afectaron a una sola).
    Ahora hay una funcion publica en el repositorio y la relectura bajo lock
    (regla 4) queda de ese lado.
    """
    backend_root = Path(__file__).resolve().parents[2]
    path = backend_root / "modules/public_api/router.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    privados = sorted(
        f"repo.{node.attr} (linea {node.lineno})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "repo"
        and node.attr.startswith("_")
    )
    assert not privados, f"el router usa metodos privados del repo: {privados}"
