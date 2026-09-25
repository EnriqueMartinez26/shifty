"""Lista blanca de lo que se guarda de Mercado Pago (L3-01, PV-14).

La funcion pura que usa el camino del webhook, la conciliacion y la
preferencia. Los casos de punta a punta estan en
``tests/integration/test_pago_de_mp_minimizado.py``.
"""

from __future__ import annotations

from modules.payments.minimization import (
    minimize_payment_payload,
    minimize_preference_payload,
)


def test_el_pago_conserva_la_lista_blanca_y_descarta_el_resto() -> None:
    minimo = minimize_payment_payload(
        {
            "id": "evt-1",
            "type": "payment",
            "action": "payment.updated",
            "status": "approved",
            "payer": {"email": "x@example.com"},
            "data": {
                "id": "mp-1",
                "status": "approved",
                "transaction_amount": 100.0,
                "currency_id": "ARS",
                "collector_id": 99,
                "preference_id": "pref-1",
                "external_reference": "turno:ref",
                "date_approved": "2026-09-25",
                "live_mode": True,
                "metadata": {
                    "appointment_id": "t1",
                    "store_id": "s1",
                    "store_public_id": "p1",
                    "payment_id": "c1",
                    "otro": "x",
                },
                "payer": {"email": "x@example.com"},
                "card": {"last_four_digits": "1234"},
            },
        }
    )
    assert minimo == {
        "id": "evt-1",
        "type": "payment",
        "action": "payment.updated",
        "status": "approved",
        "data": {
            "id": "mp-1",
            "status": "approved",
            "transaction_amount": 100.0,
            "currency_id": "ARS",
            "collector_id": 99,
            "preference_id": "pref-1",
            "external_reference": "turno:ref",
            "date_approved": "2026-09-25",
            "live_mode": True,
            "metadata": {
                "appointment_id": "t1",
                "store_id": "s1",
                "store_public_id": "p1",
                "payment_id": "c1",
            },
        },
    }


def test_un_valor_compuesto_fuera_de_data_no_pasa_aunque_la_clave_este_permitida() -> (
    None
):
    minimo = minimize_payment_payload(
        {"status": {"payer": "x@example.com"}, "data": "no es un dict"}
    )
    assert minimo == {}


def test_la_preferencia_guarda_solo_el_id_y_los_links() -> None:
    assert minimize_preference_payload(
        {
            "id": "pref-1",
            "init_point": "https://mp/1",
            "sandbox_init_point": "https://sandbox/1",
            "external_reference": "turno:ref",
            "payer": {"email": "x@example.com"},
            "items": [{"title": "Consulta"}],
            "collector_id": 1,
        }
    ) == {
        "id": "pref-1",
        "init_point": "https://mp/1",
        "sandbox_init_point": "https://sandbox/1",
        "external_reference": "turno:ref",
    }
