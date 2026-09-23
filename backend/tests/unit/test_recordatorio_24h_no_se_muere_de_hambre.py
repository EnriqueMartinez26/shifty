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


def _pendiente(turno: Any, pending_column: str | None) -> bool:
    if pending_column is None:
        return turno.reminder_24h_sent_at is None or turno.reminder_2h_sent_at is None
    return getattr(turno, pending_column) is None


class _RepoConVentana:
    """Repo que respeta la ventana y el tope, como el SQL real.

    El ``_FakeRepo`` de ``test_notifications_resilience`` devuelve siempre las
    mismas filas: no sirve para ver la inanicion, que es exactamente un
    problema de ventana + orden + tope.
    """

    filas: list[Any] = []
    claims: list[tuple[str, str]] = []
    consultas: list[tuple[datetime, datetime, int | None, str | None]] = []

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_upcoming_for_reminders(
        self,
        starts_after: datetime,
        starts_before: datetime,
        *,
        pending_column: str | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        """Filtra por ventana, por columna pendiente y por tope, como el SQL.

        Sin ``pending_column`` reproduce el predicado que tenia la consulta
        hasta el v-diff de AUD2-B4-04: ``24h IS NULL OR 2h IS NULL``, que
        deja pasar los turnos que ya recibieron la etapa pedida.
        """
        _RepoConVentana.consultas.append(
            (starts_after, starts_before, limit, pending_column)
        )
        dentro = [
            fila
            for fila in _RepoConVentana.filas
            if starts_after <= fila[0].starts_at < starts_before
            and _pendiente(fila[0], pending_column)
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
async def test_los_turnos_con_el_24h_ya_mandado_no_le_comen_el_lote_al_fresco(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V-diff de AUD2-B4-04 (2026-09-20): la inanicion seguia por otro lado.

    Sintoma: la ventana por etapa no alcanzaba. El repositorio conservaba
    ``OR(reminder_24h_sent_at IS NULL, reminder_2h_sent_at IS NULL)``, asi
    que la ventana de 24 h ``(now+3h, now+24h]`` devolvia tambien los turnos
    que YA tenian el de 24 h (todos tienen el de 2 h en NULL), ordenados
    primero por ``starts_at``. Con mas de ``limit`` turnos en las proximas
    21 h, los candidatos frescos (a ~23 h) quedaban al final y el tope los
    cortaba. El fake anterior no modelaba las columnas y no lo veia.
    """
    now = datetime.now(timezone.utc)
    filas = []
    for i in range(4):
        fila = _turno(now, 5 + i / 100, f"ya-avisado-{i}")
        fila[0].reminder_24h_sent_at = now - timedelta(hours=19)
        filas.append(fila)
    filas.append(_turno(now, 23, "manana"))
    enviados = _preparar(monkeypatch, filas)

    await tasks.process_due_appointment_reminders(now=now, limit=3)

    assert "manana" in enviados, "el turno fresco de 24 h quedo afuera del tope"
    assert ("manana", "reminder_24h_sent_at") in _RepoConVentana.claims
    # Los ya avisados no vuelven a mandarse ni ocupan lugar en el lote.
    assert enviados == ["manana"]
    assert [consulta[3] for consulta in _RepoConVentana.consultas] == [
        "reminder_2h_sent_at",
        "reminder_24h_sent_at",
    ]


@pytest.mark.asyncio
async def test_cada_etapa_pide_su_propia_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [])

    await tasks.process_due_appointment_reminders(now=now, lookahead_hours=48)

    assert len(_RepoConVentana.consultas) == 2, "una consulta por etapa"
    (desde_2h, hasta_2h, tope_2h, col_2h), (desde_24h, hasta_24h, tope_24h, col_24h) = (
        _RepoConVentana.consultas
    )
    # Cada ventana pide SU columna: la de 24 h no puede traer turnos que ya
    # recibieron el de 24 h solo porque les falta el de 2 h.
    assert (col_2h, col_24h) == ("reminder_2h_sent_at", "reminder_24h_sent_at")
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
    for desde, hasta, _, _ in _RepoConVentana.consultas:
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
