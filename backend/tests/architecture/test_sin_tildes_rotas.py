"""Ningun literal de string de la app tiene un acento perdido como ``?``.

S-12, 2026-09-18. Sintoma: tres mensajes que llegan al usuario tenian un ``?``
literal donde iba una letra acentuada (verificado a nivel de bytes, no es un
problema de consola): "Uno o m?s servicios..." en ``modules/staff/repository.py``
y "cambiar la configuraci?n del negocio" dos veces en ``modules/stores/router.py``.
Es la huella de un archivo que paso por una codificacion sin esos caracteres y
volvio con ``?`` en su lugar.

La guarda recorre con ``ast`` los literales de string de ``modules/`` y
``core/`` (no una regex sobre el archivo: asi no ve comentarios ni confunde un
``?`` de una expresion) y falla ante una letra, ``?`` y una minuscula pegadas:
el patron de un acento perdido. Un ``?`` legitimo va con el literal exacto en
``EXCEPCIONES``, con su motivo.
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
RAICES = ("modules", "core")
ACENTO_PERDIDO = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]\?[a-záéíóúñ]")

# (ruta relativa a backend/, fragmento exacto que dispara el patron) -> motivo.
EXCEPCIONES: dict[tuple[str, str], str] = {
    # Falsos positivos: separador de query string en una URL armada con
    # f-string ("/settings?tab=...", "/mercadopago?store_id=..."), no un acento.
    ("modules/payments/router.py", "s?t"): "query string de URL",
    ("modules/payments/service.py", "o?s"): "query string de URL",
}


def _hallazgos() -> list[tuple[str, int, str]]:
    encontrados: list[tuple[str, int, str]] = []
    for raiz in RAICES:
        for ruta in sorted((BACKEND / raiz).rglob("*.py")):
            relativa = ruta.relative_to(BACKEND).as_posix()
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=relativa)
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)):
                    continue
                for coincidencia in ACENTO_PERDIDO.finditer(nodo.value):
                    fragmento = coincidencia.group(0)
                    if (relativa, fragmento) in EXCEPCIONES:
                        continue
                    encontrados.append((relativa, nodo.lineno, fragmento))
    return encontrados


def test_ningun_literal_tiene_un_acento_perdido() -> None:
    hallazgos = _hallazgos()
    assert not hallazgos, "literales con un acento perdido como '?':\n" + "\n".join(
        f"  {ruta}:{linea}: {fragmento!r}" for ruta, linea, fragmento in hallazgos
    )


def test_las_excepciones_siguen_vigentes() -> None:
    """Una excepcion que ya no matchea se borra: si no, esconde un regreso."""
    vivos: set[tuple[str, str]] = set()
    for raiz in RAICES:
        for ruta in sorted((BACKEND / raiz).rglob("*.py")):
            relativa = ruta.relative_to(BACKEND).as_posix()
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=relativa)
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                    for coincidencia in ACENTO_PERDIDO.finditer(nodo.value):
                        vivos.add((relativa, coincidencia.group(0)))
    obsoletas = sorted(set(EXCEPCIONES) - vivos)
    assert not obsoletas, f"excepciones que ya no aplican: {obsoletas}"
