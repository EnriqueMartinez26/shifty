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


def test_reembolso_sobre_turno_confirmado_lo_mantiene_confirmado() -> None:
    """Decision de negocio explicita, no comportamiento por omision.

    Devolver la sena no implica que la tienda no vaya a atender. Si ademas
    quiere soltar el horario, existe cancel().
    """
    from modules.payments.service import sync_appointment_with_payment

    appointment = _appointment("confirmed")
    sync_appointment_with_payment(appointment, PaymentStatus.REFUNDED.value)
    assert appointment.status == "confirmed"


def test_reembolso_sobre_turno_esperando_pago_lo_cancela() -> None:
    from modules.payments.service import sync_appointment_with_payment

    appointment = _appointment("pending_payment")
    sync_appointment_with_payment(appointment, PaymentStatus.REFUNDED.value)
    assert appointment.status == "cancelled"


def test_el_conjunto_de_estados_terminales_es_el_documentado() -> None:
    """Contrato cruzado con el frontend.

    ``BookingStatus.isFinalized()`` en frontend/src/domain/value-objects/
    replica esta lista. No hay forma de verificar la equivalencia entre
    lenguajes en tiempo de compilacion, asi que este test la congela: si alguien
    agrega un estado absorbente al backend, CI falla aca y el mensaje indica
    que hay que actualizar el frontend.
    """
    terminales = {
        origen
        for origen, destinos in ALLOWED_STATUS_TRANSITIONS.items()
        if not destinos
    }
    assert terminales == TERMINAL_APPOINTMENT, (
        "Cambio el conjunto de estados terminales. Actualiza tambien "
        "TERMINAL_STATUSES en frontend/src/domain/value-objects/BookingStatus.ts"
    )


def test_los_horarios_de_la_tienda_son_hora_argentina() -> None:
    """Un negocio que abre 09:00 abre a las 09:00 de Argentina, no UTC.

    Antes los horarios se combinaban con .replace(tzinfo=utc), asi que una
    tienda que cargaba 09:00 terminaba aceptando reservas a las 06:00 hora
    local. El cliente elegia un horario y al dueno le aparecia otro.
    """
    from datetime import date, time

    from core.utils import local_to_utc

    # Argentina es UTC-3 todo el ano: no aplica horario de verano.
    assert local_to_utc(date(2026, 8, 30), time(9, 0)).hour == 12
    assert local_to_utc(date(2026, 1, 15), time(9, 0)).hour == 12
    assert local_to_utc(date(2026, 8, 30), time(18, 0)).hour == 21
