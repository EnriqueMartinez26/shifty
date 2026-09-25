"""Guardas de transicion compartidas por los caminos que cancelan turnos.

El grafo permite ``pending_payment -> cancelled`` porque un reembolso legitimo
lo necesita (``sync_appointment_with_payment``). Lo que no puede pasar es que
esa transicion la dispare *un actor humano* por una via que no venza antes el
cobro y la preferencia remota de Mercado Pago. Desde D2 (2026-09-25) la
cancelacion del panel si los vence (``AppointmentService.cancel``); los caminos
que no, se frenan con estas guardas.

La guarda pertenece al evento, no al endpoint: por eso vive aca y no duplicada
en cada router.
"""

from __future__ import annotations

from core.exceptions import AppException
from modules.appointments.model import Appointment, AppointmentStatus


def awaits_payment(appointment: Appointment, *, live_payment: bool) -> bool:
    """El turno tiene un cobro vivo.

    Unica condicion de la regla: el turno espera su sena (``pending_payment``)
    O tiene un ``Payment`` vivo (``live_payment``: un link generado desde el
    panel sobre un turno confirmado, decision del dueno D1, 2026-09-25). La
    guarda es pura: ``live_payment`` lo calcula el repositorio
    (``payments.repository.live_charge_of``) antes de llamarla.

    La usan la guarda del cliente (``public_api.service.client_cancel_denial``,
    con un mensaje para el cliente) y la de la reprogramacion del panel (abajo).
    """
    return appointment.status == AppointmentStatus.PENDING_PAYMENT.value or live_payment


def reject_cancellation_while_awaiting_payment(
    appointment: Appointment, *, live_payment: bool
) -> None:
    """Bloquea la reprogramacion del panel sobre un turno con cobro vivo.

    Reprogramar cancela el original sin vencer su cobro: el link de pago
    quedaria activo y el cliente podria pagar un turno que ya no existe. Para
    soltarlo estan ``cancel()`` (cualquier personal, vence el cobro: D2) y
    ``release_pending()`` (admin). Desde D2 ``cancel()`` ya no la usa.
    """
    if awaits_payment(appointment, live_payment=live_payment):
        raise AppException(
            message=(
                "Un turno con un pago pendiente no se reprograma: cancelalo "
                "(se vence el link de pago) y cargá uno nuevo"
            ),
            http_status=409,
            error_code="PAYMENT_APPOINTMENT_REQUIRES_RELEASE",
        )


__all__ = ["awaits_payment", "reject_cancellation_while_awaiting_payment"]
