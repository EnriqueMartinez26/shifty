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
        "_validate_payment_identity",
        "_validate_payment_link",
        "_avisar_al_dueno",
        "_sync_appointment",
        # Revision 4R de la PR #104.
        "enrich_mercadopago_webhook_payload",
        "alert_integrity_rejection",
        "alert_unexpected_payment_failure",
        # Re-revision de la PR #112.
        "_resolver_link",
        "_es_de_otro_pago",
        "_es_evento_de_otro_pago",
        "_evento_de_otro_pago",
        "_avisar_reverso_de_otro_pago",
    ],
    "modules/payments/router.py": [
        "mercadopago_webhook",
        "mercadopago_oauth_callback",
        "_aplicar_y_anotar_en_el_inbox",
    ],
    "modules/payments/service.py": [
        "create_panel_payment_preference",
        "_panel_link_phase_two",
        "_upsert_payment_preference",
        "_attach_provider_link",
        "prepare_mercadopago_preference",
        "expire_live_charge",
    ],
    "modules/payments/application.py": ["manual_confirm"],
    # Revision de 3b977a9..6c84d46 (#1, RECHAZO): _reconcile llego a 81.
    "modules/payments/jobs.py": [
        "_reconcile",
        "_conciliar_un_cobro",
        "_marcar_conciliados",
        "_enrich_inbox_payloads",
        "_remote_payments_for_reconciliation",
        "_fetch_remote_payment",
        "_expire_unpaid_appointments",
        "_vencer_o_rescatar",
        "_fetch_remote_payments",
        "_vencer_una_pagina",
        "_rescatar_o_retener",
        "_process_webhook_inbox_batch",
        "_other_payment_reversal_notification",
    ],
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
