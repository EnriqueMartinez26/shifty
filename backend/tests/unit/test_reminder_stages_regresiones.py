"""Regresiones de las etapas de recordatorio (review 2026-09-11)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import modules.notifications.tasks as tasks
from modules.notifications.reminders import STAGE_24H, STAGE_2H, due_stages

NOW = datetime(2026, 9, 11, 12, 52, tzinfo=timezone.utc)


def _turno(starts_at: datetime, **marcas: object) -> SimpleNamespace:
    campos: dict[str, object] = {
        "starts_at": starts_at,
        "created_at": starts_at - timedelta(days=3),
        "reminder_24h_sent_at": None,
        "reminder_2h_sent_at": None,
    }
    campos.update(marcas)
    return SimpleNamespace(**campos)


def test_tras_una_caida_no_salen_los_dos_mails_con_minutos_de_diferencia() -> None:
    # El worker vuelve a falta de 2h08m: con el piso pegado al lead del de 2h,
    # mandaba el de 24h y 15 minutos despues el de 2h.
    turno = _turno(NOW + timedelta(hours=2, minutes=8))
    assert due_stages(turno, NOW) == []

    # Recien cuando entra en la ventana del de 2h se manda ese, y solo ese.
    mas_tarde = NOW + timedelta(minutes=15)
    assert [s.name for s in due_stages(turno, mas_tarde)] == ["2h"]


def test_el_piso_del_de_24h_esta_por_encima_del_lead_del_de_2h() -> None:
    assert STAGE_24H.floor > STAGE_2H.lead, (
        "con piso == lead los dos recordatorios se pisan"
    )


@pytest.mark.asyncio
async def test_el_recordatorio_no_se_manda_al_email_tecnico_noreply(
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
        phone="5491155550000",
        email="5491155550000@storeABC.noreply",
        details={"public_id": "appt-1", "service": "Corte", "staff": "Ana"},
    )

    assert resultado["status"] == "skipped"
    assert enviados == [], "un .noreply rebota y ensucia la reputacion del remitente"
