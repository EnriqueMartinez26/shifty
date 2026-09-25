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
from typing import Any

import pytest

import modules.notifications.tasks as tasks
from tests.unit.test_notifications_resilience import _fila, _preparar


def _destinos(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    destinos: list[str | None] = []

    async def recordar(
        *,
        email: str | None,
        details: dict[str, Any],
        smtp: Any = None,
    ) -> dict[str, str]:
        destinos.append(email)
        return {"status": "sent", "channel": "email", "to": email or ""}

    monkeypatch.setattr(tasks, "notify_client_reminder", recordar)
    return destinos


@pytest.mark.asyncio
async def test_el_recordatorio_usa_el_email_de_la_reserva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    fila = _fila(now, 23)
    # El registro quedo con el email viejo; esta reserva trajo el actual.
    fila[3].email = "viejo@example.com"
    fila[0].client_email = "nuevo@example.com"
    _preparar(monkeypatch, [fila])
    destinos = _destinos(monkeypatch)

    resultado = await tasks.process_due_appointment_reminders(now=now)

    assert resultado["published"] == 1
    assert destinos == ["nuevo@example.com"]


@pytest.mark.asyncio
async def test_sin_email_en_la_reserva_cae_al_del_registro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    fila = _fila(now, 23)
    fila[3].email = "registro@example.com"
    fila[0].client_email = None
    _preparar(monkeypatch, [fila])
    destinos = _destinos(monkeypatch)

    await tasks.process_due_appointment_reminders(now=now)

    assert destinos == ["registro@example.com"]
