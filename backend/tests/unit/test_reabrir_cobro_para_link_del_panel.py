"""``Payment.reopen_for_panel_link``: ``expired -> pending`` fuera del grafo general.

Revision de perf/f4-pay (2026-09-25, #5, opcion b del coordinador). Regenerar
desde el panel el link de un cobro ``expired`` sellaba el link nuevo sobre un
cobro que seguia ``expired`` (el grafo no tiene ``expired -> pending`` y
``apply_status`` lo ignoraba en silencio): el link nuevo era pagable pero no
era un cobro vivo, asi que D1/D2 no lo veian.

La arista NO se agrega a ``ALLOWED_PAYMENT_TRANSITIONS``: ese grafo lo usa
tambien el webhook, y un ``in_process`` tardio de la preferencia vieja
reabriria un cobro vencido (quizas de un turno ya cancelado). La reapertura
es un metodo aparte de la entidad, con un solo llamador permitido: la
regeneracion del panel (``create_panel_payment_preference``), bajo el lock
del turno y con un turno no soltado. Este archivo fija las tres cosas.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from modules.payments.model import (
    ALLOWED_PAYMENT_TRANSITIONS,
    Payment,
    PaymentStatus,
)

BACKEND = Path(__file__).resolve().parents[2]


def _cobro(estado: PaymentStatus) -> Payment:
    return Payment(
        store_id="tienda",
        appointment_id="turno",
        amount=Decimal("100"),
        status=estado.value,
        preference_id="pref-nueva",
    )


def test_el_grafo_general_no_reabre_un_cobro_vencido() -> None:
    assert ALLOWED_PAYMENT_TRANSITIONS["expired"] == {"approved", "manual_confirmed"}
    cobro = _cobro(PaymentStatus.EXPIRED)
    assert cobro.apply_status(PaymentStatus.PENDING.value) is False
    assert cobro.status == PaymentStatus.EXPIRED.value


def test_reabrir_pasa_un_vencido_a_pendiente() -> None:
    cobro = _cobro(PaymentStatus.EXPIRED)

    assert cobro.reopen_for_panel_link() is True
    assert cobro.status == PaymentStatus.PENDING.value
    assert cobro.is_live_charge


@pytest.mark.parametrize(
    "estado",
    [s for s in PaymentStatus if s is not PaymentStatus.EXPIRED],
)
def test_reabrir_solo_aplica_a_un_vencido(estado: PaymentStatus) -> None:
    cobro = _cobro(estado)

    assert cobro.reopen_for_panel_link() is False
    assert cobro.status == estado.value


def test_reabrir_exige_un_link_real() -> None:
    """Sin link nuevo (o con el placeholder) no hay nada que cobrar."""
    cobro = _cobro(PaymentStatus.EXPIRED)
    cobro.preference_id = "pref_turno"

    assert cobro.reopen_for_panel_link() is False
    assert cobro.status == PaymentStatus.EXPIRED.value


def test_el_unico_llamador_es_la_regeneracion_del_panel() -> None:
    llamadores: list[str] = []
    for archivo in (BACKEND / "modules").rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for funcion in ast.walk(arbol):
            if not isinstance(funcion, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for nodo in ast.walk(funcion):
                if (
                    isinstance(nodo, ast.Attribute)
                    and nodo.attr == "reopen_for_panel_link"
                    and isinstance(nodo.ctx, ast.Load)
                ):
                    llamadores.append(
                        f"{archivo.relative_to(BACKEND).as_posix()}::{funcion.name}"
                    )
    assert sorted(set(llamadores)) == [
        "modules/payments/service.py::create_panel_payment_preference"
    ], llamadores
