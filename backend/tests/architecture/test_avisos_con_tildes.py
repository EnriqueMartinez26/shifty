"""Los avisos y los mails que lee una persona van con tildes.

2026-10-14. Sintoma: el aviso del panel decia "Agusuto murillo pago la seña de
$100.00 ... El turno quedo confirmado automaticamente." Los textos de los
avisos al dueño (``payments/jobs.py``, ``waitlist/offers.py``) y de los mails
al cliente (``notifications/tasks.py``, ``otp/service.py``) estaban escritos
sin tildes, y los importes salian con ``${amount}`` en vez de ``format_ars``.

Complementa a ``test_sin_tildes_rotas.py`` (S-12, un ``?`` donde iba una
letra acentuada): esta guarda busca palabras que en castellano SIEMPRE llevan
tilde y que aparecian sin ella. Mira solo los literales de esos cuatro
archivos que pueden llegar a una persona: no los docstrings ni los nombres de
eventos de log.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ARCHIVOS = (
    "modules/payments/jobs.py",
    "modules/waitlist/offers.py",
    "modules/notifications/tasks.py",
    "modules/otp/service.py",
)
# Palabras que nunca se escriben sin tilde (ni como otra palabra valida).
SIN_TILDE = re.compile(
    r"\b("
    r"automaticamente|suscripcion|pagina|devolucion|codigo|verificacion|"
    r"direccion|telefono|politica|traves|proximo|despues|recibis|tenes|"
    r"podes|queres|reconoces|tenias|habias|volvio|devolvio|abrio|libero|"
    r"recibio|aplico|dia|dias"
    r")\b",
    re.IGNORECASE,
)


def _es_docstring(nodo: ast.AST, padres: dict[ast.AST, ast.AST]) -> bool:
    padre = padres.get(nodo)
    return isinstance(padre, ast.Expr)


def _es_de_log(nodo: ast.AST, padres: dict[ast.AST, ast.AST]) -> bool:
    actual: ast.AST | None = nodo
    while actual is not None:
        if isinstance(actual, ast.Call):
            funcion = actual.func
            if isinstance(funcion, ast.Attribute) and isinstance(
                funcion.value, ast.Name
            ):
                if funcion.value.id == "logger":
                    return True
        actual = padres.get(actual)
    return False


def _hallazgos() -> list[str]:
    encontrados: list[str] = []
    for relativa in ARCHIVOS:
        arbol = ast.parse((BACKEND / relativa).read_text(encoding="utf-8"))
        padres = {
            hijo: padre
            for padre in ast.walk(arbol)
            for hijo in ast.iter_child_nodes(padre)
        }
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)):
                continue
            if _es_docstring(nodo, padres) or _es_de_log(nodo, padres):
                continue
            for palabra in SIN_TILDE.findall(nodo.value):
                encontrados.append(f"{relativa}:{nodo.lineno}: {palabra!r}")
    return encontrados


def test_los_avisos_y_mails_no_tienen_palabras_sin_tilde() -> None:
    hallazgos = _hallazgos()
    assert not hallazgos, "texto para personas sin tilde:\n" + "\n".join(hallazgos)
