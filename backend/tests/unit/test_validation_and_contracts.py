import struct
from datetime import datetime, timedelta, timezone

import pytest

from core.responses import is_canonical_payload
from core.validation import reject_control_chars, reject_payload_control_chars
from modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentNotesStaffUpdate,
)
from modules.stores.media import exceeds_pixel_budget


def _png_with_dims(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0d"
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x00" * 32
    )


def test_reject_control_chars_bloquea_bidi_y_zero_width() -> None:
    venenos = [
        chr(0x202E) + "nombre",  # RTL override (Trojan Source)
        "cli" + chr(0x200B) + "ente",  # zero-width space
        "a" + chr(0x2066) + "b",  # bidi isolate
        "x" + chr(0xFEFF) + "y",  # BOM
        "n\x00m",  # NUL
    ]
    for veneno in venenos:
        with pytest.raises(ValueError):
            reject_control_chars(veneno)
    # Texto normal (incluyendo saltos de linea legitimos) pasa.
    assert reject_control_chars("Juan Pérez\nnota") == "Juan Pérez\nnota"


def test_exceeds_pixel_budget_detecta_bomba_de_pixeles() -> None:
    assert exceeds_pixel_budget(_png_with_dims(30000, 30000), "image/png") is True
    assert exceeds_pixel_budget(_png_with_dims(512, 512), "image/png") is False
    # Sin dimensiones determinables no bloquea (best-effort; el cap de 2MB acota).
    sin_ihdr = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert exceeds_pixel_budget(sin_ihdr, "image/png") is False


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
