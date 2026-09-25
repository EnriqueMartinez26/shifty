"""Regla 29: las funciones del camino del cobro no pasan de 80 lineas.

Revision de perf/f4-pay (2026-09-25, RECHAZO #4): la rama habia dejado
``apply_mercadopago_webhook_payload`` en 83 lineas (ya era deuda y la rama la
empeoro). Esta lista fija las funciones que la rama toco o creo en el camino
del cobro: una validacion nueva se extrae, no se apila.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
LIMITE = 80

FUNCIONES = {
    "modules/payments/processing.py": [
        "apply_mercadopago_webhook_payload",
        "find_payment_for_webhook",
        "_validate_payment_integrity",
        "_avisar_al_dueno",
        "_sync_appointment",
    ],
    "modules/payments/service.py": [
        "create_panel_payment_preference",
        "_upsert_payment_preference",
        "_attach_provider_link",
        "prepare_mercadopago_preference",
        "expire_live_charge",
    ],
    "modules/payments/application.py": ["manual_confirm"],
}


def _largos(archivo: str) -> dict[str, int]:
    arbol = ast.parse((BACKEND / archivo).read_text(encoding="utf-8"))
    return {
        nodo.name: (nodo.end_lineno or nodo.lineno) - nodo.lineno + 1
        for nodo in ast.walk(arbol)
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.parametrize(
    ("archivo", "funcion"),
    [(archivo, f) for archivo, nombres in FUNCIONES.items() for f in nombres],
)
def test_la_funcion_entra_en_el_limite(archivo: str, funcion: str) -> None:
    largos = _largos(archivo)
    assert funcion in largos, f"{archivo}::{funcion} no existe"
    assert largos[funcion] <= LIMITE, f"{archivo}::{funcion}: {largos[funcion]} lineas"
