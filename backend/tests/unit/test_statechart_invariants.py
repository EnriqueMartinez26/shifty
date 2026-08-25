"""Invariantes de las dos regiones del statechart.

No prueban endpoints: prueban que el grafo sea inescapable y que exista una
sola fuente de verdad por region.
"""

import pytest

from core.exceptions import InvalidStatusTransitionException
from infrastructure.persistence.models.appointment import (
    ALLOWED_STATUS_TRANSITIONS,
)
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import (
    ALLOWED_PAYMENT_TRANSITIONS,
    PaymentStatus,
    can_apply_payment_status,
)

TERMINAL_APPOINTMENT = {"cancelled", "completed", "absent", "expired"}


def _appointment(status: str) -> Appointment:
    return Appointment(
        status=status,
        store_id="store",
        service_id="service",
        staff_id="staff",
        duration_minutes=30,
    )


def test_status_no_se_puede_escribir_sin_pasar_por_el_guard() -> None:
    """La unica via de escritura es apply_status_transition()."""
    appointment = _appointment("pending")
    with pytest.raises(AttributeError):
        appointment.status = "completed"
    assert appointment.status == "pending"


def test_los_estados_terminales_son_absorbentes() -> None:
    for terminal in TERMINAL_APPOINTMENT:
        assert ALLOWED_STATUS_TRANSITIONS[terminal] == set()
        appointment = _appointment(terminal)
        for target in AppointmentStatus:
            if target.value == terminal:
                continue
            with pytest.raises(InvalidStatusTransitionException):
                appointment.apply_status_transition(target)


def test_no_se_puede_cancelar_un_turno_completado() -> None:
    appointment = _appointment("completed")
    with pytest.raises(InvalidStatusTransitionException):
        appointment.apply_status_transition(AppointmentStatus.CANCELLED)


def test_can_transition_to_y_el_guard_comparten_fuente() -> None:
    """Antes eran dos diccionarios que coincidian por disciplina."""
    for origen in AppointmentStatus:
        for destino in AppointmentStatus:
            if origen is destino:
                continue
            consulta = origen.can_transition_to(destino)
            appointment = _appointment(origen.value)
            try:
                appointment.apply_status_transition(destino)
                aplicada = True
            except InvalidStatusTransitionException:
                aplicada = False
            assert consulta == aplicada, f"{origen.value} -> {destino.value}"


def test_un_pago_devuelto_no_puede_revivir() -> None:
    """El ratchet anterior dejaba pasar refunded -> approved."""
    assert not can_apply_payment_status(
        PaymentStatus.REFUNDED.value, PaymentStatus.APPROVED.value
    )
    assert ALLOWED_PAYMENT_TRANSITIONS[PaymentStatus.REFUNDED.value] == set()


def test_un_pago_acreditado_no_se_degrada() -> None:
    for asentado in (
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    ):
        for degradado in (
            PaymentStatus.PENDING.value,
            PaymentStatus.REJECTED.value,
            PaymentStatus.EXPIRED.value,
        ):
            assert not can_apply_payment_status(asentado, degradado)


def test_la_conciliacion_puede_recuperar_un_cobro_vencido() -> None:
    """Si la plata entro de verdad, el sistema tiene que poder registrarlo."""
    assert can_apply_payment_status(
        PaymentStatus.EXPIRED.value, PaymentStatus.APPROVED.value
    )
    assert can_apply_payment_status(
        PaymentStatus.REJECTED.value, PaymentStatus.APPROVED.value
    )
