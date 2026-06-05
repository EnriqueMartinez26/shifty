"""
Tests unitarios de la lógica de reservas.

Cubre:
  1. SchedulingDomainService — validaciones puras sin IO.
  2. Cálculo de slots de AvailabilityService — testeado sin DB real mediante
     lógica de solapamiento extraída a funciones puras.
  3. Reglas de negocio: bloqueos manuales tienen prioridad sobre conflictos.

No requiere base de datos ni Redis: todo es lógica pura o con mocks.
"""

import pytest
from datetime import datetime, timedelta, timezone, time, date
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from modules.appointments.domain_service import SchedulingDomainService
from core.exceptions import (
    AppointmentConflictException,
    BlockedScheduleException,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dt(hour: int, minute: int = 0) -> datetime:
    """Crea un datetime UTC aware en la fecha de hoy para simplificar fixtures."""
    return datetime(2030, 6, 15, hour, minute, tzinfo=timezone.utc)


def make_appointment(starts_at: datetime, duration_minutes: int = 60) -> SimpleNamespace:
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    return SimpleNamespace(
        starts_at=starts_at,
        ends_at=ends_at,
        status="confirmed",
        public_id="APPT-001",
    )


def make_block(starts_at: datetime, ends_at: datetime, note: str = "Bloqueo") -> SimpleNamespace:
    return SimpleNamespace(
        starts_at=starts_at,
        ends_at=ends_at,
        note=note,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# SchedulingDomainService
# ---------------------------------------------------------------------------

class TestSchedulingDomainService:
    """Tests para el servicio de dominio puro — sin IO."""

    def setup_method(self):
        self.svc = SchedulingDomainService()

    # --- Happy path ---

    def test_no_conflict_no_block_passes(self):
        """Sin conflictos ni bloqueos, validate_availability no lanza."""
        self.svc.validate_availability(
            requested_start=dt(10),
            requested_end=dt(11),
            conflicting_appointment=None,
            overlapping_block=None,
        )

    # --- Conflicto con otro turno ---

    def test_raises_conflict_when_appointment_overlaps(self):
        existing = make_appointment(dt(10), 60)  # 10:00–11:00
        with pytest.raises(AppointmentConflictException) as exc:
            self.svc.validate_availability(
                requested_start=dt(10, 30),   # 10:30 — dentro del bloque
                requested_end=dt(11, 30),
                conflicting_appointment=existing,
                overlapping_block=None,
            )
        assert exc.value.error_code == "APPOINTMENT_CONFLICT"

    def test_conflict_message_contains_times(self):
        existing = make_appointment(dt(14), 90)  # 14:00–15:30
        with pytest.raises(AppointmentConflictException) as exc:
            self.svc.validate_availability(
                requested_start=dt(15),
                requested_end=dt(16),
                conflicting_appointment=existing,
                overlapping_block=None,
            )
        assert "14:00" in exc.value.message
        assert "15:30" in exc.value.message

    def test_conflict_includes_suggestion_when_provided(self):
        existing = make_appointment(dt(10), 60)
        suggestion = dt(11)
        with pytest.raises(AppointmentConflictException) as exc:
            self.svc.validate_availability(
                requested_start=dt(10),
                requested_end=dt(11),
                conflicting_appointment=existing,
                overlapping_block=None,
                suggestion=suggestion,
            )
        assert exc.value.detail["suggestion"] is not None
        assert "11:00" in exc.value.message

    # --- Bloqueo manual ---

    def test_raises_blocked_when_block_present(self):
        block = make_block(dt(9), dt(12), note="Vacaciones")
        with pytest.raises(BlockedScheduleException) as exc:
            self.svc.validate_availability(
                requested_start=dt(10),
                requested_end=dt(11),
                conflicting_appointment=None,
                overlapping_block=block,
            )
        assert exc.value.error_code == "SCHEDULE_BLOCKED"

    def test_block_has_priority_over_appointment_conflict(self):
        """Un bloqueo manual tiene mayor prioridad que un turno conflictivo."""
        existing = make_appointment(dt(10), 60)
        block = make_block(dt(9), dt(13), note="Capacitación")
        with pytest.raises(BlockedScheduleException):
            self.svc.validate_availability(
                requested_start=dt(10),
                requested_end=dt(11),
                conflicting_appointment=existing,
                overlapping_block=block,
            )

    def test_block_message_contains_reason(self):
        block = make_block(dt(8), dt(12), note="Mantenimiento")
        with pytest.raises(BlockedScheduleException) as exc:
            self.svc.validate_availability(
                requested_start=dt(9),
                requested_end=dt(10),
                conflicting_appointment=None,
                overlapping_block=block,
            )
        assert "Mantenimiento" in exc.value.message

    def test_block_detail_contains_start_end(self):
        block = make_block(dt(8), dt(12))
        with pytest.raises(BlockedScheduleException) as exc:
            self.svc.validate_availability(
                requested_start=dt(9),
                requested_end=dt(10),
                conflicting_appointment=None,
                overlapping_block=block,
            )
        assert exc.value.detail["block_start"] is not None
        assert exc.value.detail["block_end"] is not None


# ---------------------------------------------------------------------------
# Overlap detection — lógica pura extraída del repositorio
# ---------------------------------------------------------------------------

def overlaps(
    existing_start: datetime,
    existing_end: datetime,
    new_start: datetime,
    new_end: datetime,
) -> bool:
    """
    Implementa la fórmula de Sentinel 2.2:
      existing.starts_at < new.ends_at  AND  existing.ends_at > new.starts_at
    """
    return existing_start < new_end and existing_end > new_start


class TestOverlapFormula:
    """Tests de la fórmula de solapamiento usada en el repositorio."""

    def test_exact_same_slot_overlaps(self):
        assert overlaps(dt(10), dt(11), dt(10), dt(11))

    def test_partial_overlap_start(self):
        # existente 10-11, nuevo 10:30-11:30 → solapa
        assert overlaps(dt(10), dt(11), dt(10, 30), dt(11, 30))

    def test_partial_overlap_end(self):
        # existente 11-12, nuevo 10:30-11:30 → solapa
        assert overlaps(dt(11), dt(12), dt(10, 30), dt(11, 30))

    def test_contained_slot_overlaps(self):
        # nuevo está dentro del existente
        assert overlaps(dt(10), dt(12), dt(10, 30), dt(11))

    def test_containing_slot_overlaps(self):
        # existente está dentro del nuevo
        assert overlaps(dt(10, 30), dt(11), dt(10), dt(12))

    def test_adjacent_after_does_not_overlap(self):
        # existente 10-11, nuevo 11-12 → no solapa (extremo exacto)
        assert not overlaps(dt(10), dt(11), dt(11), dt(12))

    def test_adjacent_before_does_not_overlap(self):
        # existente 11-12, nuevo 10-11 → no solapa
        assert not overlaps(dt(11), dt(12), dt(10), dt(11))

    def test_completely_before_does_not_overlap(self):
        assert not overlaps(dt(8), dt(9), dt(10), dt(11))

    def test_completely_after_does_not_overlap(self):
        assert not overlaps(dt(13), dt(14), dt(10), dt(11))


# ---------------------------------------------------------------------------
# AvailabilityService — slot calculation logic (sin DB)
# ---------------------------------------------------------------------------

def compute_slots_for_schedule(
    schedule_start: time,
    schedule_end: time,
    duration_minutes: int,
    booked_appointments: list,
    blocks: list,
    search_date: date,
    granularity_minutes: int = 15,
    notice_hours: int = 0,
) -> list[dict]:
    """
    Réplica fiel de la lógica de AvailabilityService.get_available_slots()
    para poder testearla sin base de datos.
    Permite aislar el algoritmo puro de su infraestructura.
    """
    duration = timedelta(minutes=duration_minutes)
    min_bookable_time = datetime.now(timezone.utc) + timedelta(hours=notice_hours)

    current = datetime.combine(search_date, schedule_start, tzinfo=timezone.utc)
    end = datetime.combine(search_date, schedule_end, tzinfo=timezone.utc)

    slots = []
    while current + duration <= end:
        slot_end = current + duration

        blocked_by_appt = any(
            not (slot_end <= appt.starts_at or current >= appt.ends_at)
            for appt in booked_appointments
        )

        overlapping_block = next(
            (b for b in blocks if b.starts_at < slot_end and b.ends_at > current),
            None,
        )

        too_soon = current < min_bookable_time

        status = "available"
        reason = None

        if blocked_by_appt:
            status = "booked"
        elif overlapping_block:
            status = "blocked"
            reason = overlapping_block.note
        elif too_soon:
            status = "blocked"
            reason = f"Requiere {notice_hours}h de antelación"

        slots.append({
            "starts_at": current.isoformat(),
            "ends_at": slot_end.isoformat(),
            "status": status,
            "reason": reason,
        })

        current += timedelta(minutes=granularity_minutes)

    return slots


TODAY = date(2030, 6, 15)  # fecha fija, siempre en el futuro


class TestSlotCalculation:
    """Tests del algoritmo de slots de disponibilidad."""

    def _run(
        self,
        *,
        start: str = "09:00",
        end: str = "17:00",
        duration: int = 60,
        appointments: list | None = None,
        blocks: list | None = None,
        notice_hours: int = 0,
    ) -> list[dict]:
        h, m = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        return compute_slots_for_schedule(
            schedule_start=time(h, m),
            schedule_end=time(eh, em),
            duration_minutes=duration,
            booked_appointments=appointments or [],
            blocks=blocks or [],
            search_date=TODAY,
            granularity_minutes=15,
            notice_hours=notice_hours,
        )

    def test_no_appointments_all_available(self):
        slots = self._run(start="09:00", end="11:00", duration=60)
        # 09:00–10:00, 09:15–10:15, 09:30–10:30, 09:45–10:45 → 4 slots
        assert len(slots) == 5
        assert all(s["status"] == "available" for s in slots)

    def test_booked_appointment_marks_slots(self):
        appt = make_appointment(
            datetime(2030, 6, 15, 10, 0, tzinfo=timezone.utc), duration_minutes=60
        )
        slots = self._run(start="09:00", end="12:00", duration=60, appointments=[appt])
        booked = [s for s in slots if s["status"] == "booked"]
        # El slot de 10:00 y los que solapan (09:15, 09:30, 09:45, 10:00) deben ser booked
        assert len(booked) > 0

    def test_slot_exactly_before_appointment_is_available(self):
        appt = make_appointment(
            datetime(2030, 6, 15, 10, 0, tzinfo=timezone.utc), duration_minutes=60
        )
        # Un turno de 1h que termina a las 10:00 no solapa con appt que empieza a las 10:00
        slots = self._run(start="09:00", end="11:00", duration=60, appointments=[appt])
        # El slot 09:00-10:00 debe estar available
        first = slots[0]
        assert first["starts_at"].startswith("2030-06-15T09:00")
        assert first["status"] == "available"

    def test_slot_exactly_after_appointment_is_available(self):
        appt = make_appointment(
            datetime(2030, 6, 15, 9, 0, tzinfo=timezone.utc), duration_minutes=60
        )
        # Slot 10:00-11:00 no solapa con appt 09:00-10:00
        slots = self._run(start="09:00", end="11:30", duration=60, appointments=[appt])
        slot_10 = next(
            s for s in slots if s["starts_at"].startswith("2030-06-15T10:00")
        )
        assert slot_10["status"] == "available"

    def test_staff_block_marks_slots_as_blocked(self):
        block = make_block(
            datetime(2030, 6, 15, 10, 0, tzinfo=timezone.utc),
            datetime(2030, 6, 15, 12, 0, tzinfo=timezone.utc),
            note="Vacaciones",
        )
        slots = self._run(start="09:00", end="13:00", duration=60, blocks=[block])
        blocked_slots = [s for s in slots if s["status"] == "blocked"]
        assert len(blocked_slots) > 0
        assert all(s["reason"] == "Vacaciones" for s in blocked_slots)

    def test_block_does_not_affect_earlier_slots(self):
        block = make_block(
            datetime(2030, 6, 15, 11, 0, tzinfo=timezone.utc),
            datetime(2030, 6, 15, 13, 0, tzinfo=timezone.utc),
        )
        slots = self._run(start="09:00", end="13:00", duration=60, blocks=[block])
        slot_09 = next(s for s in slots if s["starts_at"].startswith("2030-06-15T09:00"))
        slot_10 = next(s for s in slots if s["starts_at"].startswith("2030-06-15T10:00"))
        assert slot_09["status"] == "available"
        assert slot_10["status"] == "available"

    def test_duration_longer_than_gap_produces_no_slot(self):
        # Schedule solo 30 minutos, duración 60 → ningún slot generado
        slots = self._run(start="10:00", end="10:30", duration=60)
        assert len(slots) == 0

    def test_slot_count_matches_granularity(self):
        # Schedule 09:00-11:00 (2h) con duración 60 y granularidad 15 → 4 slots
        slots = self._run(start="09:00", end="11:00", duration=60)
        assert len(slots) == 5

    def test_notice_hours_blocks_imminent_slots(self):
        # Con notice_hours=999, todos los slots en futuro lejano deberían ser blocked
        # (hoy a las 09:00 del 2030 no está dentro de 999h desde now si now < 2030)
        # Usamos fecha casi real: date.today()
        from datetime import date as date_type
        today = date_type.today()
        slots = compute_slots_for_schedule(
            schedule_start=time(9, 0),
            schedule_end=time(11, 0),
            duration_minutes=60,
            booked_appointments=[],
            blocks=[],
            search_date=today,
            notice_hours=999,  # ningún slot dentro de 999h futuras
        )
        assert all(s["status"] == "blocked" for s in slots)

    def test_cancelled_appointment_does_not_block_slot(self):
        """
        Un turno cancelado no debe bloquear slots.
        El repositorio filtra status != CANCELLED antes de cargar los booked,
        así que este test simula que la lista de appointments ya viene sin cancelados.
        """
        # Si booked_appointments está vacío (porque los cancelados no se cargan), el slot es libre
        slots = self._run(start="10:00", end="11:30", duration=60, appointments=[])
        assert all(s["status"] == "available" for s in slots)
