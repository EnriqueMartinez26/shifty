"""``Payment.status`` es de solo lectura: la entidad aplica su transicion.

2026-09-17, hallazgo B2-08: a diferencia de ``Appointment``, ``Payment``
exponia la columna ``status`` escribible y ``ensure_payment_preference`` la
reasignaba a mano (``payment.status = "pending"``), salteando
``Payment.apply_status`` y con el la unica guarda del grafo de pagos (no hay
trigger ni CHECK en la base para ``payments``). CLAUDE.md §2 promete que
asignar ``status`` directo levanta ``AttributeError`` en las dos maquinas de
estado; para el pago era mentira.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from modules.payments.model import (
    ALLOWED_PAYMENT_TRANSITIONS,
    Payment,
    PaymentStatus,
    can_apply_payment_status,
)


def _pago(estado: str = PaymentStatus.PENDING.value) -> Payment:
    # `status=` sigue siendo el nombre publico del constructor (service, tests).
    return Payment(
        store_id="tienda", appointment_id="turno", amount=Decimal("10"), status=estado
    )


def test_asignar_status_directo_levanta_attribute_error() -> None:
    pago = _pago()
    with pytest.raises(AttributeError):
        pago.status = PaymentStatus.APPROVED.value
    assert pago.status == PaymentStatus.PENDING.value


def test_el_constructor_acepta_status_y_la_propiedad_lo_lee() -> None:
    assert _pago(PaymentStatus.APPROVED.value).status == PaymentStatus.APPROVED.value
    assert _pago().status == PaymentStatus.PENDING.value


def test_apply_status_sigue_siendo_el_unico_camino_y_respeta_el_grafo() -> None:
    for origen in PaymentStatus:
        for destino in PaymentStatus:
            if origen is destino:
                continue
            pago = _pago(origen.value)
            aplicada = pago.apply_status(destino.value)
            assert aplicada == can_apply_payment_status(origen.value, destino.value), (
                f"{origen.value} -> {destino.value}"
            )
            esperado = destino.value if aplicada else origen.value
            assert pago.status == esperado, f"{origen.value} -> {destino.value}"
    # Y el grafo mismo no cambio: refunded sigue siendo terminal.
    assert ALLOWED_PAYMENT_TRANSITIONS[PaymentStatus.REFUNDED.value] == set()


def test_status_sigue_sirviendo_para_filtrar_en_queries() -> None:
    # A nivel clase la propiedad tiene que seguir siendo una columna usable en
    # WHERE/GROUP BY (conciliacion, jobs): se compila contra la columna `status`.
    sql = str(select(Payment.id).where(Payment.status == "approved"))
    assert "payments.status" in sql
