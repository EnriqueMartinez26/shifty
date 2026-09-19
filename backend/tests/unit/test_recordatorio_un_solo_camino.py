"""El recordatorio al cliente sale por un solo camino: notify_client_reminder.

X-08 (2026-09-18, codigo muerto): ``send_appointment_reminder`` quedo sin
llamadores cuando el recordatorio paso a elegir canal (WhatsApp y despues
mail) en ``notify_client_reminder``. Ademas NO aplicaba
``is_deliverable_email``: era un atajo que, si alguien lo volvia a llamar,
mandaba al email tecnico ``.noreply``. Se borra; la guarda vive en
``notify_client_reminder`` (``test_reminder_stages_regresiones``
``::test_el_recordatorio_no_se_manda_al_email_tecnico_noreply``).
"""

from __future__ import annotations

from typing import Any

import pytest

import modules.notifications.tasks as tasks


def test_no_queda_un_segundo_camino_de_recordatorio() -> None:
    assert not hasattr(tasks, "send_appointment_reminder")


@pytest.mark.asyncio
async def test_el_unico_camino_no_manda_al_email_tecnico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enviados: list[str] = []

    async def buzon(to: str, subject: str, body: str) -> bool:
        enviados.append(to)
        return True

    async def sin_whatsapp(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(tasks, "_send_email", buzon)
    monkeypatch.setattr(tasks, "_send_whatsapp", sin_whatsapp)

    resultado = await tasks.notify_client_reminder(
        phone=None,
        email="5491100000000@store1.noreply",
        details={"public_id": "appt-x08", "service": "Corte", "staff": "Ana"},
    )
    assert resultado["status"] == "skipped"
    assert enviados == []
