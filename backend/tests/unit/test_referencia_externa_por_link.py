"""Cada link de pago tiene su propia ``external_reference`` (revision de perf/f4-pay).

2026-09-25, hallazgo de la revision de 5d41644: la integridad del webhook
distinguia un pago del link VIEJO de uno del link nuevo solo por
``preference_id``, y el pago de Mercado Pago no lo trae (lo dice el README
del emulador, ``tests/e2e/README.md``). Con ``external_reference`` = id del
turno para todos los links del cobro, un ``approved`` tardio del link viejo
pasaba la integridad y el cobro regenerado quedaba ``approved`` con el link
nuevo vivo: el cliente podia pagar dos veces.

Ahora cada link lleva un nonce propio (``Payment.link_ref``) en la
``external_reference`` (``<turno>:<nonce>``), una senal que controla Shifty.
Un cobro sin ``link_ref`` (links creados antes del deploy) sigue usando el id
del turno solo: los links en vuelo siguen matcheando su propia generacion.
"""

from __future__ import annotations

from decimal import Decimal

from modules.payments.model import (
    Payment,
    PaymentStatus,
    appointment_id_from_reference,
    external_reference_for,
)


def test_la_referencia_legada_es_el_id_del_turno() -> None:
    assert external_reference_for("TURNO1", None) == "TURNO1"
    assert appointment_id_from_reference("TURNO1") == "TURNO1"


def test_la_referencia_con_nonce_se_parsea_al_turno() -> None:
    referencia = external_reference_for("TURNO1", "N1")

    assert referencia == "TURNO1:N1"
    assert appointment_id_from_reference(referencia) == "TURNO1"


def test_la_referencia_vigente_es_la_del_link_actual() -> None:
    cobro = Payment(
        store_id="tienda",
        appointment_id="TURNO1",
        amount=Decimal("100"),
        status=PaymentStatus.PENDING.value,
    )
    assert cobro.current_external_reference == "TURNO1"
    cobro.link_ref = "N2"
    assert cobro.current_external_reference == "TURNO1:N2"
