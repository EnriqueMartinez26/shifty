"""Guardas de transicion compartidas por todos los caminos que cancelan turnos.

El grafo permite ``pending_payment -> cancelled`` porque un reembolso legitimo
lo necesita (``sync_appointment_with_payment``). Lo que no puede pasar es que
esa transicion la dispare *un actor humano* por una via que no venza antes la
preferencia remota de Mercado Pago.

La guarda pertenece al evento, no al endpoint: por eso vive aca y no duplicada
en cada router.
"""

from __future__ import annotations

from core.exceptions import AppException
from modules.appointments.model import Appointment, AppointmentStatus


def awaits_payment(appointment: Appointment) -> bool:
    """El turno tiene un cobro vivo: solo lo suelta ``release()``.

    Unica condicion de la regla: la usan la guarda del panel (abajo) y la del
    cliente (``public_api.service.client_cancel_denial``), que responde el
    mismo codigo con un mensaje para el cliente.
    """
    return appointment.status == AppointmentStatus.PENDING_PAYMENT.value


def reject_cancellation_while_awaiting_payment(appointment: Appointment) -> None:
    """Bloquea la cancelacion iniciada por una persona sobre un turno con cobro vivo.

    Liberar uno de estos turnos exige pasar por ``release()``, que vence la
    preferencia en Mercado Pago antes de soltar el horario. Cancelarlo por otra
    via dejaria el link de pago activo y el cliente podria pagar un turno que ya
    no existe.
    """
    if awaits_payment(appointment):
        raise AppException(
            message=(
                "Los turnos con un pago pendiente deben liberarse desde "
                "la accion protegida para administradores"
            ),
            http_status=409,
            error_code="PAYMENT_APPOINTMENT_REQUIRES_RELEASE",
        )


__all__ = ["awaits_payment", "reject_cancellation_while_awaiting_payment"]
