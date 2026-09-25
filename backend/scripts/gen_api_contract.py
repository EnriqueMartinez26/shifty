"""Genera docs/API_CONTRACT.md desde el esquema real (`app.openapi()`).

El contrato se arma en proceso importando `app` de `main`: no hay JSON
intermedio ni subproceso. La salida es determinista (grupos, rutas, metodos y
esquemas ordenados) y no depende del entorno: el titulo y la version de la API
salen de settings y cambian entre el stack y los tests, asi que no se
publican. La unica linea variable es el pie (fecha y commit), que queda fuera
de la comparacion.

tests/architecture/test_api_contract_doc.py falla en CI si el cuerpo del
documento commiteado deja de coincidir con `render_contract(app.openapi())`.

Regenerar desde el codigo del working tree, nunca desde una imagen: los
contenedores corren la imagen construida, sin bind mount, y un `exec`
generaria el contrato del ultimo build, no del codigo que se commitea.

Con las dependencias del backend en el host (desde backend/):

    uv run python scripts/gen_api_contract.py           # escribe el archivo
    uv run python scripts/gen_api_contract.py --check   # sale 1 si hay deriva

Sin uv en el host (desde la raiz del repo): se monta el codigo en /src y se
usa el Python de la imagen. Montarlo sobre /app tapa el .venv de la imagen
(/app/.venv) y falla con "No module named 'fastapi'".

    MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
        -v ./backend:/src -w /src backend \
        /app/.venv/bin/python scripts/gen_api_contract.py --stdout \
        --commit $(git rev-parse --short HEAD) > docs/API_CONTRACT.md
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_DOC = REPO_ROOT / "docs" / "API_CONTRACT.md"

FOOTER_PREFIX = "Generado desde app.openapi() el "
UNKNOWN_COMMIT = "desconocido"
MAX_DIFF_LINES = 80

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "format",
)
_SHORT_HASH = re.compile(r"^[0-9a-f]{4,40}$")

JsonObject = dict[str, Any]
Operation = tuple[str, str, JsonObject]


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _escape(text: str) -> str:
    # Las celdas de tabla markdown no admiten '|' ni saltos de linea.
    return text.replace("|", "\\|").replace("\n", " ").strip()


class _ContractRenderer:
    """Arma el markdown y registra que esquemas quedaron referenciados."""

    def __init__(self, schema: JsonObject) -> None:
        self._spec = schema
        self._schemas: JsonObject = schema.get("components", {}).get("schemas", {})
        self._referenced: set[str] = set()

    def _ref_name(self, ref: str) -> str:
        name = ref.rsplit("/", 1)[-1]
        self._referenced.add(name)
        return name

    def _type_of(self, node: JsonObject | None) -> str:
        if not node:
            return "any"
        if "$ref" in node:
            return self._ref_name(node["$ref"])
        if "anyOf" in node or "oneOf" in node:
            options: list[JsonObject] = node.get("anyOf") or node.get("oneOf") or []
            return " | ".join(self._type_of(option) for option in options)
        if "allOf" in node:
            return " & ".join(self._type_of(part) for part in node["allOf"])
        if "enum" in node:
            return "enum(" + ", ".join(_dump(value) for value in node["enum"]) + ")"
        if "const" in node:
            return "const " + _dump(node["const"])
        kind = node.get("type", "any")
        if isinstance(kind, list):
            kind = " | ".join(kind)
        if kind == "array":
            return f"array<{self._type_of(node.get('items'))}>"
        extra = node.get("additionalProperties")
        if kind == "object" and isinstance(extra, dict):
            return f"object<string, {self._type_of(extra)}>"
        return str(kind)

    @staticmethod
    def _constraints(node: JsonObject | None) -> str:
        if not node:
            return ""
        found: list[str] = []
        candidates = [node, *node.get("anyOf", []), *node.get("oneOf", [])]
        for candidate in candidates:
            for key in CONSTRAINT_KEYS:
                if key in candidate:
                    item = f"{key}={_dump(candidate[key])}"
                    if item not in found:
                        found.append(item)
        if "default" in node:
            found.append(f"default={_dump(node['default'])}")
        return ", ".join(found)

    def _shape(self, node: JsonObject | None) -> str:
        if not node:
            return "_(sin esquema)_"
        return f"`{self._type_of(node)}`"

    def _parameter_lines(self, params: list[JsonObject]) -> list[str]:
        lines = [
            "Parameters:",
            "",
            "| in | name | required | type | constraints |",
            "|---|---|---|---|---|",
        ]
        for param in params:
            node = param.get("schema")
            required = "yes" if param.get("required") else "no"
            lines.append(
                f"| {param.get('in')} | `{param.get('name')}` | {required} "
                f"| {_escape(self._type_of(node))} "
                f"| {_escape(self._constraints(node))} |"
            )
        lines.append("")
        return lines

    def _operation_lines(self, path: str, method: str, op: JsonObject) -> list[str]:
        lines = [f"### {method.upper()} {path}", ""]
        if op.get("summary"):
            lines.append(f"- Summary: {_escape(op['summary'])}")
        if op.get("operationId"):
            lines.append(f"- operationId: `{op['operationId']}`")
        if op.get("deprecated"):
            lines.append("- Deprecated: true")
        if "security" in op:
            lines.append(f"- Security: `{json.dumps(op['security'])}`")
        lines.append("")

        params = op.get("parameters", [])
        if params:
            lines += self._parameter_lines(params)

        body = op.get("requestBody")
        if body:
            required = "required" if body.get("required") else "optional"
            lines += [f"Request body ({required}):", ""]
            for content_type, media in body.get("content", {}).items():
                lines.append(f"- `{content_type}`: {self._shape(media.get('schema'))}")
            lines.append("")

        responses: JsonObject = op.get("responses", {})
        if responses:
            lines += ["Responses:", ""]
            for code in sorted(responses):
                response = responses[code]
                content = response.get("content", {})
                description = _escape(response.get("description", ""))
                if not content:
                    lines.append(f"- `{code}` {description}")
                for content_type, media in content.items():
                    lines.append(
                        f"- `{code}` {description} — `{content_type}`: "
                        f"{self._shape(media.get('schema'))}"
                    )
            lines.append("")
        return lines

    def _group_operations(self) -> dict[str, list[Operation]]:
        groups: dict[str, list[Operation]] = {}
        for path, item in self._spec.get("paths", {}).items():
            for method in METHODS:
                if method not in item:
                    continue
                op = item[method]
                tags = op.get("tags") or []
                group = tags[0] if tags else (path.strip("/").split("/")[0] or "/")
                groups.setdefault(group, []).append((path, method, op))
        return groups

    def _walk_refs(self, node: object) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                self._ref_name(node["$ref"])
            for value in node.values():
                self._walk_refs(value)
        elif isinstance(node, list):
            for value in node:
                self._walk_refs(value)

    def _referenced_closure(self) -> set[str]:
        # Cierre transitivo: un esquema referenciado arrastra los que usa.
        done: set[str] = set()
        while pending := self._referenced - done:
            for name in sorted(pending):
                done.add(name)
                self._walk_refs(self._schemas.get(name, {}))
        return done

    def _schema_lines(self, name: str) -> list[str]:
        node: JsonObject = self._schemas.get(name, {})
        lines = [f"### {name}", ""]
        if node.get("type") == "object" or "properties" in node:
            props: JsonObject = node.get("properties", {})
            required = set(node.get("required", []))
            if props:
                lines += [
                    "| field | type | required | constraints |",
                    "|---|---|---|---|",
                ]
                for field, field_node in props.items():
                    lines.append(
                        f"| `{field}` | {_escape(self._type_of(field_node))} "
                        f"| {'yes' if field in required else 'no'} "
                        f"| {_escape(self._constraints(field_node))} |"
                    )
            else:
                lines.append("_(object sin propiedades declaradas)_")
        else:
            extra = self._constraints(node)
            suffix = f" ({extra})" if extra else ""
            lines.append(f"Type: `{self._type_of(node)}`{suffix}")
        lines.append("")
        return lines

    def render(self) -> str:
        groups = self._group_operations()
        n_paths = len(self._spec.get("paths", {}))
        n_ops = sum(len(ops) for ops in groups.values())
        lines = [
            "# API Contract",
            "",
            "Generado automaticamente desde `app.openapi()` del backend (FastAPI);"
            " no editar a mano. Regenerar con `backend/scripts/gen_api_contract.py`"
            " (el comando esta en su docstring).",
            "",
            f"- OpenAPI: {self._spec.get('openapi')}",
            f"- Paths: {n_paths} — Operaciones: {n_ops}",
            "",
        ]
        for group in sorted(groups, key=lambda name: (name.lower(), name)):
            lines += [f"## {group}", ""]
            ops = sorted(groups[group], key=lambda op: (op[0], METHODS.index(op[1])))
            for path, method, op in ops:
                lines += self._operation_lines(path, method, op)

        lines += ["## Schemas", ""]
        for name in sorted(self._referenced_closure(), key=lambda n: (n.lower(), n)):
            lines += self._schema_lines(name)
        return "\n".join(lines) + "\n"


def render_contract(schema: JsonObject) -> str:
    """Cuerpo markdown del contrato, SIN la linea de pie."""
    return _ContractRenderer(schema).render()


def split_footer(document: str) -> tuple[str, str | None]:
    """Separa el cuerpo del pie. Devuelve (cuerpo, pie o None si no hay pie)."""
    lines = document.splitlines(keepends=True)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].startswith(FOOTER_PREFIX):
        return "".join(lines[:-1]), lines[-1].rstrip("\n")
    return document, None


def current_openapi() -> JsonObject:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from main import app

    return app.openapi()


def _git_short_hash() -> str:
    # En el contenedor puede no haber git ni repo (solo se monta backend/).
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except OSError:
        return UNKNOWN_COMMIT
    except subprocess.SubprocessError:
        return UNKNOWN_COMMIT
    commit = result.stdout.strip()
    return commit if _SHORT_HASH.match(commit) else UNKNOWN_COMMIT


def build_footer(commit: str | None) -> str:
    if commit is None:
        commit = _git_short_hash()
    elif not _SHORT_HASH.match(commit):
        raise SystemExit(f"--commit no parece un hash de git: {commit!r}")
    from core.utils import ARGENTINA_TZ

    today = datetime.now(timezone.utc).astimezone(ARGENTINA_TZ).date()
    return f"{FOOTER_PREFIX}{today.isoformat()}, commit {commit}"


def check_document(doc_path: Path, expected_body: str) -> int:
    if not doc_path.is_file():
        print(f"No existe {doc_path}; generarlo sin --check.", file=sys.stderr)
        return 1
    body, footer = split_footer(doc_path.read_text(encoding="utf-8"))
    if footer is None:
        print(f"{doc_path} no termina con el pie '{FOOTER_PREFIX}...'.")
        return 1
    if body == expected_body:
        print(f"{doc_path} coincide con app.openapi().")
        return 0
    diff = list(
        difflib.unified_diff(
            body.splitlines(),
            expected_body.splitlines(),
            fromfile=f"{doc_path} (commiteado)",
            tofile="app.openapi() (actual)",
            lineterm="",
        )
    )
    print("\n".join(diff[:MAX_DIFF_LINES]))
    if len(diff) > MAX_DIFF_LINES:
        print(f"... ({len(diff) - MAX_DIFF_LINES} lineas mas de diff)")
    print(f"\n{doc_path} quedo desactualizado: regenerarlo (ver docstring).")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera docs/API_CONTRACT.md desde app.openapi()."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="sale 1 con un diff si el documento difiere del esquema actual",
    )
    mode.add_argument(
        "--stdout",
        action="store_true",
        help="imprime cuerpo + pie en stdout en vez de escribir el archivo",
    )
    parser.add_argument(
        "--output",
        "--doc",
        dest="doc",
        type=Path,
        default=DEFAULT_DOC,
        help=f"documento a escribir o verificar (default: {DEFAULT_DOC})",
    )
    parser.add_argument(
        "--commit",
        help="hash corto para el pie; por defecto `git rev-parse --short HEAD`",
    )
    args = parser.parse_args(argv)

    body = render_contract(current_openapi())
    doc: Path = args.doc
    if args.check:
        return check_document(doc, body)

    document = body + build_footer(args.commit) + "\n"
    if args.stdout:
        # Bytes UTF-8 explicitos: el locale del contenedor puede no ser UTF-8.
        sys.stdout.buffer.write(document.encode("utf-8"))
        sys.stdout.flush()
        return 0
    if not doc.parent.is_dir():
        print(
            f"No existe {doc.parent} (el contenedor corre la imagen, sin "
            "docs/): usar --stdout y redirigir en el host.",
            file=sys.stderr,
        )
        return 1
    doc.write_text(document, encoding="utf-8", newline="\n")
    print(f"Escrito {doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
