"""Guardas de los caminos del panel que sueltan o mueven un turno.

Rol y duenio del turno (``require_can_manage_appointment``, D-20260929-03) y
turno ya empezado (``reject_already_started``, D-20260929-05); abajo, la
guarda del cobro vivo, compartida por los caminos que sueltan un turno.

El grafo permite ``pending_payment -> cancelled`` porque un reembolso legitimo
lo necesita (``sync_appointment_with_payment``). Lo que no puede pasar es que
un actor humano suelte un turno con cobro vivo sin vencer antes el cobro y la
preferencia remota de Mercado Pago.

Desde 2026-09-25 el panel ya no se frena al cancelar: cancelar (y
reprogramar un turno con un link del panel) vence el cobro en la misma
transaccion (``payments.service.expire_live_charge``, D2). Reprogramar un
``pending_payment`` si se frena: ``reject_reschedule_with_pending_deposit``
(decision de Mateo 2026-09-25: opcion A).
La guarda que frenaba al panel (``reject_cancellation_while_awaiting_payment``)
se borro con su ultimo llamador; lo que protegia (que el link quedara vivo
sobre un turno cancelado) lo sostiene ``expire_live_charge`` y lo prueban
``test_cancelar_desde_el_panel_vence_el_cobro.py`` y
``test_reprogramar_del_panel_vence_el_cobro.py``. El cliente sigue frenado:
``public_api.service.client_cancel_denial`` usa ``awaits_payment``.
"""

from __future__ import annotations

from http import HTTPStatus

from core.exceptions import AppException, PermissionDeniedException
from core.roles import (
    ROLE_PROFESSIONAL,
    ROLE_RECEPTIONIST,
    STORE_MANAGERS,
    canonical_role,
)
from core.utils import ensure_utc_aware, now_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.users.model import User

# Quienes sueltan o mueven CUALQUIER turno de la tienda desde el panel
# (D-20260929-03). El profesional, solo los de su agenda.
_ANY_APPOINTMENT_OF_THE_STORE = STORE_MANAGERS | {ROLE_RECEPTIONIST}


def require_can_manage_appointment(
    appointment: Appointment, actor: User, action: str
) -> None:
    """Cancelar o reprogramar desde el panel: rol y duenio del turno (403 neutro).

    Decision del duenio D-20260929-03: el admin de la tienda (y el
    superadmin) y la recepcion, cualquier turno de la tienda; el profesional,
    solo los asignados a su ficha (``Staff.id == User.id``, como el alta del
    panel). Cualquier otro rol, nada. Antes cualquier usuario autenticado de
    la tienda cancelaba o movia el turno de cualquier profesional
    (2026-09-29). El rol sale del ``User`` releido de la base por request
    (regla 1), nunca del JWT. Se llama con el turno ya lockeado y leido.
    """
    role = canonical_role(actor)
    if role in _ANY_APPOINTMENT_OF_THE_STORE:
        return
    if role == ROLE_PROFESSIONAL and appointment.staff_id == actor.id:
        return
    raise PermissionDeniedException(action)


def reject_already_started(appointment: Appointment) -> None:
    """Un turno que ya empezo no se cancela desde el panel: 409 neutro.

    Decision del duenio D-20260929-05: lo que corresponde es completarlo o
    marcar la ausencia. Cancelarlo publicaba un cupo "liberado" que ya paso y
    borraba el rastro de si el cliente vino. Comparacion en UTC (regla 24).
    Un turno terminal no llega aca con este motivo: sigue respondiendo lo de
    siempre (``APPOINTMENT_ALREADY_CANCELLED`` o la transicion invalida).
    """
    if is_active(appointment) and ensure_utc_aware(appointment.starts_at) <= now_utc():
        raise AppException(
            message="El turno ya empezo: completalo o marcá la ausencia",
            http_status=HTTPStatus.CONFLICT,
            error_code="APPOINTMENT_ALREADY_STARTED",
        )


def awaits_payment(appointment: Appointment, *, live_payment: bool) -> bool:
    """El turno tiene un cobro vivo.

    Unica condicion de la regla: el turno espera su sena (``pending_payment``)
    O tiene un ``Payment`` vivo (``live_payment``: un link generado desde el
    panel sobre un turno confirmado, decision de Mateo D1, 2026-09-25). La
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


def reject_reschedule_with_pending_deposit(appointment: Appointment) -> None:
    """Un turno con sena REQUERIDA pendiente no se reprograma desde el panel.

    Decision de Mateo 2026-09-25: opcion A. Moverlo como ``pending`` sin
    cobro (lo que se hizo mientras se decidia) perdia la sena requerida. El
    personal cobra la sena y despues lo mueve, o lo cancela (D2 vence el
    cobro). Solo ``pending_payment``: el link del panel de un turno
    confirmado no es una sena requerida y ese turno se sigue reprogramando
    (vence el link). Se llama con el turno ya lockeado, antes de tocar nada.
    """
    if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
        raise AppException(
            message="Cobrá la seña o cancelá el turno antes de moverlo",
            http_status=HTTPStatus.CONFLICT,
            error_code="DEPOSIT_PENDING_RESCHEDULE_DENIED",
        )


__all__ = [
    "awaits_payment",
    "is_active",
    "reject_already_cancelled",
    "reject_already_started",
    "reject_reschedule_with_pending_deposit",
    "reject_inactive",
    "require_can_manage_appointment",
]
