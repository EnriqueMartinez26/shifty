"""AUD2-B4-04 (2026-09-20): el tope del lote dejaba sin recordatorio de 24 h.

Sintoma: la consulta del lote traia los turnos de las proximas 48 h de TODAS
las tiendas cuyo ``reminder_24h_sent_at`` O ``reminder_2h_sent_at`` fuera NULL
-o sea, practicamente todos-, ordenados por ``starts_at`` ascendente y
cortados en ``REMINDER_BATCH_LIMIT``. La condicion de "toca mandar ahora" se
evaluaba recien en Python (``due_stages``). Como los primeros del orden son
los mas proximos, en cuanto la plataforma tiene ``limit`` turnos empezando
dentro de las proximas horas, los que estan a 24 h nunca entran al lote;
cuando por fin entran ya les faltan menos de 3 h y el piso de la etapa los
descarta (``reminders._PISO_24H``). Resultado: el cliente deja de recibir el
aviso de 24 h y recibe solo el de 2 h, sin ningun error.

Correccion: el lote pide una ventana POR ETAPA, cada una con su propio tope,
asi el ``limit`` corta sobre filas que de verdad hay que mandar y una etapa no
le come el lugar a la otra. ``lookahead_hours`` queda solo como cota superior.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import modules.notifications.tasks as tasks
from tests.unit.test_notifications_resilience import _fila, _FakeSessionFactory


class _RepoConVentana:
    """Repo que respeta la ventana y el tope, como el SQL real.

    El ``_FakeRepo`` de ``test_notifications_resilience`` devuelve siempre las
    mismas filas: no sirve para ver la inanicion, que es exactamente un
    problema de ventana + orden + tope.
    """

    filas: list[Any] = []
    claims: list[tuple[str, str]] = []
    consultas: list[tuple[datetime, datetime, int | None]] = []

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_upcoming_for_reminders(
        self,
        starts_after: datetime,
        starts_before: datetime,
        *,
        limit: int | None = None,
    ) -> list[Any]:
        _RepoConVentana.consultas.append((starts_after, starts_before, limit))
        dentro = [
            fila
            for fila in _RepoConVentana.filas
            if starts_after <= fila[0].starts_at < starts_before
        ]
        dentro.sort(key=lambda fila: fila[0].starts_at)
        return dentro[:limit] if limit is not None else dentro

    async def claim_reminder(
        self, appointment_id: str, column: str, sent_at: datetime
    ) -> bool:
        _RepoConVentana.claims.append((appointment_id, column))
        return True

    async def release_reminder(self, appointment_id: str, column: str) -> None:
        return None


def _preparar(monkeypatch: pytest.MonkeyPatch, filas: list[Any]) -> list[str | None]:
    enviados: list[str | None] = []

    async def recordar(
        *,
        phone: str | None,
        email: str | None,
        details: dict[str, Any],
        smtp: Any = None,
    ) -> dict[str, str]:
        enviados.append(details.get("public_id"))
        return {"status": "sent", "channel": "email", "to": email or ""}

    _RepoConVentana.filas = filas
    _RepoConVentana.claims = []
    _RepoConVentana.consultas = []
    monkeypatch.setattr(tasks, "AsyncSessionFactory", lambda: _FakeSessionFactory())
    monkeypatch.setattr(tasks, "notify_client_reminder", recordar)
    monkeypatch.setattr(
        "modules.appointments.repository.AppointmentRepository", _RepoConVentana
    )
    return enviados


def _turno(now: datetime, horas: float, nombre: str) -> Any:
    fila = _fila(now, horas)
    fila[0].id = nombre
    fila[0].public_id = nombre
    fila[0].created_at = now - timedelta(days=3)
    return fila


@pytest.mark.asyncio
async def test_los_turnos_de_una_hora_no_le_comen_el_lote_al_de_24h(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    # limit+1 turnos a 1 h (candidatos a la etapa de 2 h) ordenan antes que
    # el de 23 h, unico candidato a la etapa de 24 h.
    filas = [_turno(now, 1 + i / 100, f"ya-casi-{i}") for i in range(4)]
    filas.append(_turno(now, 23, "manana"))
    enviados = _preparar(monkeypatch, filas)

    resultado = await tasks.process_due_appointment_reminders(now=now, limit=3)

    assert "manana" in enviados, "el turno de 24 h nunca entro al lote"
    assert ("manana", "reminder_24h_sent_at") in _RepoConVentana.claims
    # El tope sigue vivo: la etapa de 2 h manda a lo sumo ``limit`` por corrida.
    assert len([p for p in enviados if p != "manana"]) == 3
    assert resultado["batch_full"] is True


@pytest.mark.asyncio
async def test_cada_etapa_pide_su_propia_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [])

    await tasks.process_due_appointment_reminders(now=now, lookahead_hours=48)

    assert len(_RepoConVentana.consultas) == 2, "una consulta por etapa"
    (desde_2h, hasta_2h, tope_2h), (desde_24h, hasta_24h, tope_24h) = (
        _RepoConVentana.consultas
    )
    assert desde_2h == now
    assert hasta_2h <= now + timedelta(hours=2, minutes=1)
    # El piso de la etapa de 24 h (3 h) es el arranque de su ventana: un turno
    # a menos de 3 h ya no puede recibirla.
    assert desde_24h == now + timedelta(hours=3)
    assert hasta_24h <= now + timedelta(hours=24, minutes=1)
    assert (tope_2h, tope_24h) == (tasks.REMINDER_BATCH_LIMIT,) * 2


@pytest.mark.asyncio
async def test_lookahead_corto_acota_las_ventanas_y_no_las_invierte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [_turno(now, 23, "manana")])

    resultado = await tasks.process_due_appointment_reminders(
        now=now, lookahead_hours=1
    )

    assert resultado["published"] == 0
    for desde, hasta, _ in _RepoConVentana.consultas:
        assert desde < hasta, "una ventana invertida traeria cualquier cosa"
        assert hasta <= now + timedelta(hours=1, minutes=1)


@pytest.mark.asyncio
async def test_la_tienda_apagada_se_cuenta_una_sola_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``skipped`` cuenta turnos con una etapa vencida, no filas traidas."""
    now = datetime.now(timezone.utc)
    fila = _turno(now, 23, "manana")
    fila[4].send_email_reminders = False
    _preparar(monkeypatch, [fila])

    resultado = await tasks.process_due_appointment_reminders(now=now)

    assert resultado["skipped"] == 1
    assert _RepoConVentana.claims == []
