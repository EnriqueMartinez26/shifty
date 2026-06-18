from datetime import datetime, timedelta, timezone

import pytest

from core.responses import is_canonical_payload
from core.validation import reject_payload_control_chars
from modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentNotesStaffUpdate,
)


def test_is_canonical_payload_requires_complete_envelope() -> None:
    assert is_canonical_payload({"success": True, "data": {"public_id": "appt_1"}})
    assert is_canonical_payload(
        {"success": False, "error_code": "NOT_FOUND", "message": "Missing"}
    )
    assert not is_canonical_payload({"success": True})
    assert not is_canonical_payload({"success": False})
    assert not is_canonical_payload({"data": {"public_id": "appt_1"}})


def test_reject_payload_control_chars_recurses_through_nested_structures() -> None:
    payload = {
        "notes": "Cliente amable",
        "nested": [{"name": "Ana"}, {"tags": ("uno", "dos")}],
    }

    assert reject_payload_control_chars(payload) == payload

    with pytest.raises(ValueError, match="caracteres de control"):
        reject_payload_control_chars({"notes": "Linea mala\x0b"})


def test_appointment_create_rejects_control_chars_in_notes() -> None:
    future_start = datetime.now(timezone.utc) + timedelta(days=1)

    with pytest.raises(ValueError, match="caracteres de control"):
        AppointmentCreate(
            service_id="service_123",
            staff_id="staff_123",
            starts_at=future_start,
            notes="Observacion mala\x0c",
            idempotency_key="booking-key-001",
        )


def test_appointment_notes_staff_update_rejects_control_chars_in_notes() -> None:
    with pytest.raises(ValueError, match="caracteres de control"):
        AppointmentNotesStaffUpdate(notes_staff="Nota mala\x0e")
