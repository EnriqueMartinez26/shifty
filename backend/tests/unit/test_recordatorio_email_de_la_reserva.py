"""El recordatorio va al email de ESA reserva, como los otros cinco mails.

AUD2-B4-01 (2026-09-20): los cinco mails al cliente ("reserva registrada",
"turno confirmado", "turno cancelado", "te movimos el turno" y "reserva de
nuevo") se mandan a ``appointment.client_email``, el que la persona tipeo en
esa reserva. El recordatorio era el unico que usaba ``users.email`` del
registro. Las dos direcciones divergen sin nada raro: el telefono ya tiene un
cliente con un email viejo (o con el tecnico ``.noreply``), la persona reserva
de nuevo con su email actual y, como no paso por OTP, ``adopt_contact=False``
deja el registro intacto. El recordatorio (con nombre, servicio, profesional y
horario) se iba a la casilla equivocada.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

import modules.notifications.tasks as tasks
from tests.unit.test_notifications_resilience import _fila, _preparar


@pytest.mark.asyncio
async def test_el_recordatorio_usa_el_email_de_la_reserva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    fila = _fila(now, 23)
    # El registro quedo con el email viejo; esta reserva trajo el actual.
    fila[3].email = "viejo@example.com"
    fila[0].client_email = "nuevo@example.com"
    schedules = _preparar(monkeypatch, [fila])

    resultado = await tasks.process_due_appointment_reminders(now=now)

    assert resultado["published"] == 1
    assert schedules[0][3]["args"]["email"] == "nuevo@example.com"


@pytest.mark.asyncio
async def test_sin_email_en_la_reserva_cae_al_del_registro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    fila = _fila(now, 23)
    fila[3].email = "registro@example.com"
    fila[0].client_email = None
    schedules = _preparar(monkeypatch, [fila])

    await tasks.process_due_appointment_reminders(now=now)

    assert schedules[0][3]["args"]["email"] == "registro@example.com"
