"""Cada llamada del front a la API debe matchear una ruta del backend EXACTA.

Regresion real: el front llamaba GET/POST /promotions y el backend define
/promotions/. FastAPI respondia 307 a /promotions/ SIN el prefijo /api que
agrega nginx, el navegador terminaba en el SPA (HTML) y la pagina de
Promociones crasheaba con 'filter is not a function'. Los tests no lo veian
porque el cliente ASGI sigue el redirect sin prefijo. Ahora el app tiene
redirect_slashes=False y este test audita el contrato estaticamente.
"""

import re
from pathlib import Path

from main import app

FRONTEND_SRC = Path(__file__).resolve().parents[3] / "frontend" / "src"
CALL_RE = re.compile(
    r"apiClient\.(get|post|put|patch|delete)(?:<[^(]*?>)?\(\s*([`'\"])([^`'\"]+)\2"
)


def _normalize(path: str) -> str:
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{}", path)  # template literal -> param
    return re.sub(r"\{[^}]+\}", "{}", path)


def _frontend_calls() -> set[tuple[str, str, str]]:
    assert FRONTEND_SRC.is_dir(), f"no se encontro el front en {FRONTEND_SRC}"
    calls: set[tuple[str, str, str]] = set()
    for file in FRONTEND_SRC.rglob("*.ts"):
        if ".test." in file.name:
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        for match in CALL_RE.finditer(text):
            calls.add(
                (
                    match.group(1).upper(),
                    _normalize(match.group(3)),
                    file.relative_to(FRONTEND_SRC).as_posix(),
                )
            )
    return calls


def test_las_llamadas_del_front_matchean_rutas_exactas() -> None:
    routes = {_normalize(p) for p in app.openapi()["paths"]}
    calls = _frontend_calls()
    assert calls, "no se detectaron llamadas apiClient en el front"

    # Un template literal cortado por el regex (p.ej. `/x${query ? ...}`)
    # se normaliza a su base: se acepta si la base es una ruta valida.
    def matches(path: str) -> bool:
        if path in routes:
            return True
        base = path.rstrip("{}").rstrip("/")
        return base in routes or f"{base}/" in routes and path.endswith("{}")

    slash_only = [
        (m, p, src)
        for (m, p, src) in sorted(calls)
        if not matches(p) and ((p[:-1] if p.endswith("/") else p + "/") in routes)
    ]
    assert not slash_only, (
        "Llamadas del front que solo difieren por la barra final "
        "(detras de nginx terminan en el SPA): " + repr(slash_only)
    )
