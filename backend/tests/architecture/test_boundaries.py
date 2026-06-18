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
