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


METODO = "reopen_for_panel_link"
# Codigo de produccion: todo ``backend/`` salvo tests, migraciones y entornos.
EXCLUIDOS = {"tests", "alembic", ".venv", "venv", "__pycache__"}


def _usos(arbol: ast.AST) -> list[str]:
    """Donde se usa el metodo: acceso ``x.reopen_for_panel_link`` o el nombre
    como texto (``getattr(x, "reopen_for_panel_link")``,
    ``methodcaller(...)``). Devuelve la funcion que lo contiene, o
    ``<modulo>`` si esta fuera de toda funcion."""
    usos: list[str] = []

    def recorrer(nodo: ast.AST, funcion: str) -> None:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcion = nodo.name
        if (
            isinstance(nodo, ast.Attribute)
            and nodo.attr == METODO
            and isinstance(nodo.ctx, ast.Load)
        ) or (isinstance(nodo, ast.Constant) and nodo.value == METODO):
            usos.append(funcion)
        for hijo in ast.iter_child_nodes(nodo):
            recorrer(hijo, funcion)

    recorrer(arbol, "<modulo>")
    return usos


def test_el_detector_ve_getattr_y_usos_fuera_de_funciones() -> None:
    fuente = "def f(p):\n    getattr(p, 'reopen_for_panel_link')()"
    assert _usos(ast.parse(fuente)) == ["f"]
    assert _usos(ast.parse("pago.reopen_for_panel_link()")) == ["<modulo>"]
    assert _usos(ast.parse("x = 'otra cosa'")) == []


def test_el_unico_llamador_es_la_regeneracion_del_panel() -> None:
    """Todo ``backend/`` salvo ``tests/`` y ``alembic/`` (revision de
    perf/f4-pay): tambien scripts y core, no solo ``modules/``."""
    llamadores: set[str] = set()
    for archivo in BACKEND.rglob("*.py"):
        relativo = archivo.relative_to(BACKEND)
        if EXCLUIDOS & set(relativo.parts):
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        llamadores.update(f"{relativo.as_posix()}::{f}" for f in _usos(arbol))
    assert sorted(llamadores) == [
        "modules/payments/service.py::create_panel_payment_preference"
    ], llamadores
