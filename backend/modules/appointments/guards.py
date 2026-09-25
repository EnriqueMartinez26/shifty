"""Guarda del cobro vivo, compartida por los caminos que sueltan un turno.

El grafo permite ``pending_payment -> cancelled`` porque un reembolso legitimo
lo necesita (``sync_appointment_with_payment``). Lo que no puede pasar es que
un actor humano suelte un turno con cobro vivo sin vencer antes el cobro y la
preferencia remota de Mercado Pago.

Desde 2026-09-25 el panel ya no se frena: cancelar y reprogramar vencen el
cobro en la misma transaccion (``payments.service.expire_live_charge``, D2).
La guarda que frenaba al panel (``reject_cancellation_while_awaiting_payment``)
se borro con su ultimo llamador; lo que protegia (que el link quedara vivo
sobre un turno cancelado) lo sostiene ``expire_live_charge`` y lo prueban
``test_cancelar_desde_el_panel_vence_el_cobro.py`` y
``test_reprogramar_del_panel_vence_el_cobro.py``. El cliente sigue frenado:
``public_api.service.client_cancel_denial`` usa ``awaits_payment``.
"""

from __future__ import annotations

from http import HTTPStatus

from core.exceptions import AppException
from modules.appointments.model import Appointment, AppointmentStatus


def awaits_payment(appointment: Appointment, *, live_payment: bool) -> bool:
    """El turno tiene un cobro vivo.

    Unica condicion de la regla: el turno espera su sena (``pending_payment``)
    O tiene un ``Payment`` vivo (``live_payment``: un link generado desde el
    panel sobre un turno confirmado, decision del dueno D1, 2026-09-25). La
    guarda es pura: ``live_payment`` lo calcula el repositorio
    (``payments.repository.live_charge_of``) antes de llamarla.
    """
    return appointment.status == AppointmentStatus.PENDING_PAYMENT.value or live_payment


def is_active(appointment: Appointment) -> bool:
    """El turno todavia puede soltarse (cancelarse o moverse).

    Sale del grafo de estados (``ALLOWED_STATUS_TRANSITIONS``, unica fuente):
    activo es todo estado desde el que se llega a ``cancelled``. Terminales:
    ``cancelled``, ``expired``, ``completed`` y ``absent``.
    """
    return AppointmentStatus(appointment.status).can_transition_to(
        AppointmentStatus.CANCELLED
    )


def reject_already_cancelled(appointment: Appointment) -> None:
    """Cancelar un turno ya cancelado es un conflicto, no un no-op.

    CLAUDE.md §4 ("1 exito, N-1 conflictos"): ``apply_status_transition`` deja
    pasar el mismo estado y cada cancelacion repetida republicaba el cupo
    liberado, la auditoria y el aviso al dueno. Lo usan el panel y el portal,
    con el turno ya lockeado (revision de perf/f4-pay, 2026-09-25).
    """
    if appointment.status == AppointmentStatus.CANCELLED.value:
        raise AppException(
            message="El turno ya estaba cancelado",
            http_status=HTTPStatus.CONFLICT,
            error_code="APPOINTMENT_ALREADY_CANCELLED",
        )


def reject_inactive(appointment: Appointment) -> None:
    """Un turno terminal no se reprograma: 409 neutro.

    Reprogramar cancela el original con ``apply_status_transition``, que deja
    pasar el mismo estado: un turno ya cancelado volvia a la vida como turno
    nuevo (revision de perf/f4-pay, 2026-09-25). Lo usan el panel y el portal,
    con el turno ya lockeado.
    """
    if not is_active(appointment):
        raise AppException(
            message="El turno ya no esta activo",
            http_status=HTTPStatus.CONFLICT,
            error_code="APPOINTMENT_NOT_ACTIVE",
        )


__all__ = [
    "awaits_payment",
    "is_active",
    "reject_already_cancelled",
    "reject_inactive",
]
