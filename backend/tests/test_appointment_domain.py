"""
Tests unitarios para lógica de dominio de AppointmentStatus.

Testean las reglas puras del grafo de estados sin necesidad de
instanciar modelos SQLAlchemy (que requieren una sesión de DB).
"""

import pytest
from datetime import datetime, timedelta

from modules.appointments.model import AppointmentStatus
from core.exceptions import InvalidStatusTransitionException


# ---------------------------------------------------------------------------
# Helper simple: simula el comportamiento de dominio sin ORM
# ---------------------------------------------------------------------------


class AppointmentStub:
    """
    Objeto liviano que replica la lógica de dominio de Appointment
    sin depender del ORM de SQLAlchemy.
    Ideal para tests unitarios puros.
    """

    def __init__(self, status: AppointmentStatus, starts_at: datetime):
        self.status: str = status.value
        self.starts_at: datetime = starts_at
        self.ends_at: datetime = starts_at + timedelta(minutes=30)
        self.public_id: str = "STUB-APPT-001"
        self.notes: str | None = "Test"
        self.notes_staff: str | None = None
        self.cancelled_at: datetime | None = None
        self.completed_at: datetime | None = None

    @property
    def current_status(self) -> AppointmentStatus:
        return AppointmentStatus(self.status)

    def can_be_cancelled(self) -> bool:
        return self.current_status.can_transition_to(AppointmentStatus.CANCELLED)

    def can_be_confirmed(self) -> bool:
        return self.current_status.can_transition_to(AppointmentStatus.CONFIRMED)

    def can_be_completed(self) -> bool:
        return self.current_status.can_transition_to(AppointmentStatus.COMPLETED)

    def can_be_marked_absent(self) -> bool:
        return self.current_status.can_transition_to(AppointmentStatus.ABSENT)

    def is_upcoming(self) -> bool:
        return self.starts_at > datetime.utcnow()

    def is_in_past(self) -> bool:
        return self.starts_at < datetime.utcnow()

    def apply_status_transition(self, next_status: AppointmentStatus) -> None:
        if not self.current_status.can_transition_to(next_status):
            raise InvalidStatusTransitionException(
                current=self.status,
                attempted=next_status.value,
            )
        self.status = next_status.value
        now = datetime.utcnow()
        if next_status == AppointmentStatus.CANCELLED:
            self.cancelled_at = now
        elif next_status == AppointmentStatus.COMPLETED:
            self.completed_at = now


def future() -> datetime:
    return datetime.utcnow() + timedelta(hours=2)


def past() -> datetime:
    return datetime.utcnow() - timedelta(hours=2)


# ---------------------------------------------------------------------------
# Tests: Grafo de transiciones (AppointmentStatus)
# ---------------------------------------------------------------------------


class TestAppointmentStatusGraph:
    def test_pending_to_confirmed(self):
        assert AppointmentStatus.PENDING.can_transition_to(AppointmentStatus.CONFIRMED)

    def test_pending_to_cancelled(self):
        assert AppointmentStatus.PENDING.can_transition_to(AppointmentStatus.CANCELLED)

    def test_pending_cannot_go_to_completed(self):
        assert not AppointmentStatus.PENDING.can_transition_to(
            AppointmentStatus.COMPLETED
        )

    def test_pending_cannot_go_to_absent(self):
        assert not AppointmentStatus.PENDING.can_transition_to(AppointmentStatus.ABSENT)

    def test_confirmed_to_completed(self):
        assert AppointmentStatus.CONFIRMED.can_transition_to(
            AppointmentStatus.COMPLETED
        )

    def test_confirmed_to_cancelled(self):
        assert AppointmentStatus.CONFIRMED.can_transition_to(
            AppointmentStatus.CANCELLED
        )

    def test_confirmed_to_absent(self):
        assert AppointmentStatus.CONFIRMED.can_transition_to(AppointmentStatus.ABSENT)

    def test_confirmed_cannot_go_to_pending(self):
        assert not AppointmentStatus.CONFIRMED.can_transition_to(
            AppointmentStatus.PENDING
        )

    def test_completed_is_terminal(self):
        for status in AppointmentStatus:
            assert not AppointmentStatus.COMPLETED.can_transition_to(status)

    def test_cancelled_is_terminal(self):
        for status in AppointmentStatus:
            assert not AppointmentStatus.CANCELLED.can_transition_to(status)

    def test_absent_is_terminal(self):
        for status in AppointmentStatus:
            assert not AppointmentStatus.ABSENT.can_transition_to(status)


# ---------------------------------------------------------------------------
# Tests: Métodos de dominio
# ---------------------------------------------------------------------------


class TestAppointmentDomainMethods:
    def test_can_be_cancelled_from_pending(self):
        stub = AppointmentStub(AppointmentStatus.PENDING, future())
        assert stub.can_be_cancelled() is True

    def test_can_be_cancelled_from_confirmed(self):
        stub = AppointmentStub(AppointmentStatus.CONFIRMED, future())
        assert stub.can_be_cancelled() is True

    def test_cannot_cancel_completed(self):
        stub = AppointmentStub(AppointmentStatus.COMPLETED, future())
        assert stub.can_be_cancelled() is False

    def test_cannot_cancel_already_cancelled(self):
        stub = AppointmentStub(AppointmentStatus.CANCELLED, future())
        assert stub.can_be_cancelled() is False

    def test_can_confirm_from_pending(self):
        stub = AppointmentStub(AppointmentStatus.PENDING, future())
        assert stub.can_be_confirmed() is True

    def test_cannot_confirm_again(self):
        stub = AppointmentStub(AppointmentStatus.CONFIRMED, future())
        assert stub.can_be_confirmed() is False

    def test_can_mark_absent_from_confirmed(self):
        stub = AppointmentStub(AppointmentStatus.CONFIRMED, future())
        assert stub.can_be_marked_absent() is True

    def test_cannot_mark_absent_from_pending(self):
        stub = AppointmentStub(AppointmentStatus.PENDING, future())
        assert stub.can_be_marked_absent() is False

    def test_is_upcoming_future_appointment(self):
        stub = AppointmentStub(AppointmentStatus.PENDING, future())
        assert stub.is_upcoming() is True

    def test_is_not_upcoming_past_appointment(self):
        stub = AppointmentStub(AppointmentStatus.PENDING, past())
        assert stub.is_upcoming() is False

    def test_cancel_sets_cancelled_at_timestamp(self):
        stub = AppointmentStub(AppointmentStatus.PENDING, future())
        stub.apply_status_transition(AppointmentStatus.CANCELLED)
        assert stub.status == AppointmentStatus.CANCELLED.value
        assert stub.cancelled_at is not None

    def test_complete_sets_completed_at_timestamp(self):
        stub = AppointmentStub(AppointmentStatus.CONFIRMED, future())
        stub.apply_status_transition(AppointmentStatus.COMPLETED)
        assert stub.status == AppointmentStatus.COMPLETED.value
        assert stub.completed_at is not None

    def test_absent_does_not_set_cancelled_at(self):
        stub = AppointmentStub(AppointmentStatus.CONFIRMED, future())
        stub.apply_status_transition(AppointmentStatus.ABSENT)
        assert stub.status == AppointmentStatus.ABSENT.value
        assert stub.cancelled_at is None

    def test_invalid_transition_raises_exception(self):
        """No se puede completar un turno cancelado."""
        stub = AppointmentStub(AppointmentStatus.CANCELLED, future())
        with pytest.raises(InvalidStatusTransitionException) as exc_info:
            stub.apply_status_transition(AppointmentStatus.COMPLETED)
        assert exc_info.value.error_code == "INVALID_STATUS_TRANSITION"

    def test_skip_pending_to_completed_raises(self):
        """No se puede ir de PENDING directo a COMPLETED."""
        stub = AppointmentStub(AppointmentStatus.PENDING, future())
        with pytest.raises(InvalidStatusTransitionException):
            stub.apply_status_transition(AppointmentStatus.COMPLETED)

    def test_absent_to_any_raises(self):
        """ABSENT es terminal: ninguna transición es válida."""
        stub = AppointmentStub(AppointmentStatus.ABSENT, future())
        for status in AppointmentStatus:
            with pytest.raises(InvalidStatusTransitionException):
                stub.apply_status_transition(status)
