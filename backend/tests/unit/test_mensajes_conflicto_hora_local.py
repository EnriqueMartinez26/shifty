"""La hora que ve el cliente es hora argentina (CLAUDE.md §3, bloque
"Disponibilidad, hora y avisos al cliente").

2026-09-16 (audit B7-03): ``AppointmentConflictException`` y
``BlockedScheduleException`` formateaban ``starts_at``/``ends_at`` (UTC, tal
cual salen de la base) con ``strftime("%H:%M")``. Un cliente que intentaba
reservar a las 14:00 hora argentina sobre un turno de 14:00-15:00 leia
"El profesional ya tiene un turno de 17:00 a 18:00", un horario que no existe
en la grilla que estaba mirando. El ``detail`` sigue en ISO UTC: es lo que
consume el front.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.exceptions import AppointmentConflictException, BlockedScheduleException

# 14:00-15:00 hora argentina (UTC-3) == 17:00-18:00 UTC.
CONFLICT_START = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)
CONFLICT_END = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
SUGGESTION = datetime(2026, 9, 16, 18, 30, tzinfo=timezone.utc)


def test_conflicto_de_turno_muestra_hora_argentina_y_detail_en_utc() -> None:
    exc = AppointmentConflictException(
        conflict_start=CONFLICT_START,
        conflict_end=CONFLICT_END,
        suggestion=SUGGESTION,
    )

    assert exc.message == (
        "El profesional ya tiene un turno de 14:00 a 15:00. "
        "Te sugerimos intentar a las 15:30."
    )
    assert exc.detail["conflict_start"] == "2026-09-16T17:00:00+00:00"
    assert exc.detail["conflict_end"] == "2026-09-16T18:00:00+00:00"
    assert exc.detail["suggestion"] == "2026-09-16T18:30:00+00:00"


def test_conflicto_sin_sugerencia_propone_el_fin_del_turno_en_hora_local() -> None:
    exc = AppointmentConflictException(
        conflict_start=CONFLICT_START, conflict_end=CONFLICT_END
    )

    assert exc.message == (
        "El profesional ya tiene un turno de 14:00 a 15:00. "
        "Por favor, intenta reservar a partir de las 15:00."
    )


def test_bloqueo_de_agenda_muestra_hora_argentina() -> None:
    # 10:30-12:00 hora argentina == 13:30-15:00 UTC.
    exc = BlockedScheduleException(
        reason="Almuerzo",
        block_start=datetime(2026, 9, 16, 13, 30, tzinfo=timezone.utc),
        block_end=datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc),
        suggestion=datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc),
    )

    assert exc.message == (
        "La agenda está bloqueada de 10:30 a 12:00 (Razón: Almuerzo). "
        "Podés reservar a partir de las 12:00."
    )
    assert exc.detail["block_start"] == "2026-09-16T13:30:00+00:00"


def test_un_datetime_naive_de_sqlite_se_interpreta_como_utc() -> None:
    """SQLite devuelve naive aun con DateTime(timezone=True); es UTC igual."""
    exc = AppointmentConflictException(
        conflict_start=datetime(2026, 9, 16, 17, 0),
        conflict_end=datetime(2026, 9, 16, 18, 0),
    )

    assert exc.message.startswith("El profesional ya tiene un turno de 14:00 a 15:00.")


def test_el_cambio_de_dia_se_resuelve_en_hora_local() -> None:
    """02:00 UTC es 23:00 del dia anterior en Argentina: solo cambia la hora."""
    exc = AppointmentConflictException(
        conflict_start=datetime(2026, 9, 17, 2, 0, tzinfo=timezone.utc),
        conflict_end=datetime(2026, 9, 17, 2, 30, tzinfo=timezone.utc),
    )

    assert exc.message.startswith("El profesional ya tiene un turno de 23:00 a 23:30.")
