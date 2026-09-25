"""Los recordatorios solo miran turnos futuros.

2026-09-25, decision del dueno: la tienda puede cargar un turno que ya paso
(walk-in registrado despues). Ese turno no tiene que disparar recordatorios:
cada ventana de la corrida empieza en ``now + piso`` de su etapa (piso >= 0),
asi que ``get_upcoming_for_reminders`` nunca pide un inicio anterior a ahora.
"""

from __future__ import annotations

from datetime import datetime, timezone

from modules.notifications.tasks import _reminder_windows


def test_ninguna_ventana_de_recordatorio_empieza_antes_de_ahora() -> None:
    ahora = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    ventanas = _reminder_windows(ahora, 48)

    assert ventanas
    assert all(ventana.starts_after >= ahora for ventana in ventanas)
