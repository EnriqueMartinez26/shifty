"""B4-02 (2026-09-17): el lote de recordatorios tiene tope de filas y de tiempo.

Sintoma: ``process_due_appointment_reminders`` traia TODOS los turnos de TODAS
las tiendas de la ventana de 48 h sin ``limit`` y los mandaba en serie; cada
recordatorio se reclama (``UPDATE ... WHERE col IS NULL`` + commit) ANTES de
enviarse. Con un SMTP lento el hard time limit de Celery (150 s) mataba el
proceso a mitad del lote y los turnos ya reclamados quedaban con la marca
puesta sin mail: la corrida siguiente los descartaba como enviados y ese
cliente nunca recibia el aviso.

Correccion: ``limit`` en la query (con el ``ORDER BY starts_at`` existente) y
un presupuesto de tiempo que se revisa en el ``for`` externo ANTES de reclamar
el siguiente. Lo que no entra queda con la marca en NULL y espera al tick
siguiente (beat cada 15 minutos). El reclamo sigue siendo la exclusion entre
workers (``tests/postgres/test_pg_recordatorios.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as notification_tasks
from modules.appointments.repository import AppointmentRepository
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.unit.test_notifications_resilience import _FakeRepo, _fila, _preparar


def _filas_vencidas(now: datetime, cantidad: int) -> list[Any]:
    filas = []
    for i in range(cantidad):
        fila = _fila(now, 23)
        fila[0].id = f"appt-{i}"
        fila[0].public_id = f"appt-{i}"
        filas.append(fila)
    return filas


class _RelojFalso:
    """Reloj monotonico manual: cada envio "tarda" lo que se le indique."""

    def __init__(self) -> None:
        self.ahora = 1000.0

    def monotonic(self) -> float:
        return self.ahora


@pytest.mark.asyncio
async def test_el_lote_pide_a_lo_sumo_el_tope_de_filas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, _filas_vencidas(now, 3))

    await notification_tasks.process_due_appointment_reminders(now=now)
    assert _FakeRepo.limits == [notification_tasks.REMINDER_BATCH_LIMIT]
    assert notification_tasks.REMINDER_BATCH_LIMIT >= 1

    _preparar(monkeypatch, _filas_vencidas(now, 3))
    result = await notification_tasks.process_due_appointment_reminders(
        now=now, limit=2
    )
    assert _FakeRepo.limits == [2]
    assert result["published"] == 2
    assert len(_FakeRepo.claims) == 2


@pytest.mark.asyncio
async def test_presupuesto_agotado_deja_de_reclamar_y_no_pierde_recordatorios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    enviados = _preparar(monkeypatch, _filas_vencidas(now, 5))
    reloj = _RelojFalso()
    monkeypatch.setattr(
        notification_tasks, "time", SimpleNamespace(monotonic=reloj.monotonic)
    )
    # SMTP lento: cada envio consume mas de la mitad del presupuesto.
    tardanza = notification_tasks.REMINDER_TIME_BUDGET_SECONDS * 0.6

    async def envio_lento(
        *, phone: str | None, email: str | None, details: dict[str, Any]
    ) -> dict[str, str]:
        reloj.ahora += tardanza
        enviados.append(details)
        return {"status": "sent", "channel": "email", "to": email or ""}

    monkeypatch.setattr(notification_tasks, "notify_client_reminder", envio_lento)

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    # Se reclaman y mandan dos (0 s y 54 s); al tercero el presupuesto (90 s)
    # ya esta vencido y NO se reclama: la marca queda en NULL para el proximo
    # tick en vez de quedar "enviado" sin mail bajo el SIGKILL de Celery.
    assert result["published"] == 2
    assert result["unexamined"] == 3
    assert len(enviados) == 2
    assert _FakeRepo.claims == [
        ("appt-0", "reminder_24h_sent_at"),
        ("appt-1", "reminder_24h_sent_at"),
    ]
    assert _FakeRepo.releases == []


@pytest.mark.asyncio
async def test_sin_presion_de_tiempo_el_lote_se_drena_entero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    enviados = _preparar(monkeypatch, _filas_vencidas(now, 5))

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 5
    assert result["unexamined"] == 0
    assert len(enviados) == 5


@pytest.mark.asyncio
async def test_la_query_de_recordatorios_respeta_el_limit_en_sql(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El alta publica manda "reserva registrada" contra el SMTP configurado;
    # aca no hay ninguno y cada intento espera el timeout.
    async def sin_smtp(to: str, subject: str, body: str) -> bool:
        return True

    monkeypatch.setattr(notification_tasks, "_send_email", sin_smtp)
    store, token = await register_and_login(
        client, slug="lote-recordatorios", email="lote-recordatorios@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-lote@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=1)
    await add_staff_schedule(client, token, staff, target_date=dia)
    primero = dia.replace(hour=15, minute=0, second=0, microsecond=0)
    segundo = primero + timedelta(hours=1)
    # Se reserva el mas tardio primero: el ORDER BY starts_at decide, no el
    # orden de alta.
    for indice, slot in enumerate((segundo, primero)):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": slot.isoformat(),
                "client_name": f"Cliente {indice}",
                "client_email": f"lote-{indice}@demo.com",
                "client_phone": f"+549115555{indice:04d}",
                "idempotency_key": f"lote-recordatorios-{indice:06d}",
            },
        )
        assert reserva.status_code == 201, reserva.text

    repo = AppointmentRepository(test_session)
    ventana = (dia - timedelta(days=1), dia + timedelta(days=2))
    todas = await repo.get_upcoming_for_reminders(*ventana)
    assert len(todas) == 2

    acotadas = await repo.get_upcoming_for_reminders(*ventana, limit=1)
    assert len(acotadas) == 1
    assert acotadas[0][0].starts_at.replace(tzinfo=timezone.utc) == primero
