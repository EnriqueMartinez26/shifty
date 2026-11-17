"""El scheduler persiste los recordatorios; el outbox se ocupa del SMTP.

Una falla del servidor o un reinicio del worker de recordatorios no puede
perder una etapa ya marcada: la marca y la fila ``email.send`` se guardan en
la misma transaccion. El despacho SMTP usa el outbox compartido, que limita
reintentos a fallos confirmados antes de DATA.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import pytest

import modules.notifications.tasks as notification_tasks
from tests.integration.test_recordatorios_lote_y_presupuesto import _filas_vencidas
from tests.unit.test_notifications_resilience import _FakeRepo, _preparar

_NOTIFY_REAL = notification_tasks.notify_client_reminder
COLUMNA = "reminder_24h_sent_at"


class _SmtpFalso:
    conexiones = 0
    logins = 0
    quits = 0
    noops = 0
    intentos = 0
    enviados: list[EmailMessage] = []
    caer_en_intento: set[int] = set()
    rechazar_conexion: set[int] = set()
    noop_muerto: set[int] = set()

    @classmethod
    def reset(
        cls,
        *,
        caer_en_intento: set[int] | None = None,
        rechazar_conexion: set[int] | None = None,
        noop_muerto: set[int] | None = None,
    ) -> None:
        cls.conexiones = 0
        cls.logins = 0
        cls.quits = 0
        cls.noops = 0
        cls.intentos = 0
        cls.enviados = []
        cls.caer_en_intento = caer_en_intento or set()
        cls.rechazar_conexion = rechazar_conexion or set()
        cls.noop_muerto = noop_muerto or set()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _SmtpFalso.conexiones += 1
        if _SmtpFalso.conexiones in _SmtpFalso.rechazar_conexion:
            raise smtplib.SMTPConnectError(421, b"servicio no disponible")

    # Protocolo de context manager como smtplib.SMTP (el codigo previo a B4-08
    # lo usaba con ``with``): al salir hace QUIT.
    def __enter__(self) -> "_SmtpFalso":
        return self

    def __exit__(self, *args: Any) -> None:
        self.quit()

    # Firma de smtplib: desde PV-06 se llama con ``context=``.
    def starttls(self, **_kwargs: Any) -> None:
        return None

    def login(self, *args: Any) -> None:
        _SmtpFalso.logins += 1

    def noop(self) -> tuple[int, bytes]:
        indice = _SmtpFalso.noops
        _SmtpFalso.noops += 1
        if indice in _SmtpFalso.noop_muerto:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        return (250, b"OK")

    def send_message(self, message: EmailMessage) -> None:
        intento = _SmtpFalso.intentos
        _SmtpFalso.intentos += 1
        if intento in _SmtpFalso.caer_en_intento:
            # Lo que smtplib levanta ante un timeout leyendo el 250 del DATA.
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        _SmtpFalso.enviados.append(message)

    def quit(self) -> None:
        _SmtpFalso.quits += 1

    def close(self) -> None:
        return None


def _preparar_lote(
    monkeypatch: pytest.MonkeyPatch, filas: list[Any], **fallas: set[int]
) -> None:
    _preparar(monkeypatch, filas)
    # El scheduler no llama al notifier: el correo sale desde el outbox.
    monkeypatch.setattr(notification_tasks, "notify_client_reminder", _NOTIFY_REAL)
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)
    _SmtpFalso.reset(**fallas)


@pytest.mark.asyncio
async def test_scheduler_persiste_recordatorios_sin_conectar_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    filas = _filas_vencidas(now, 5)
    # Un mail tecnico .noreply no recibe recordatorios.
    filas[1][1].name = "Corte\r\nBcc: victima@example.com"
    filas[4][3].email = "5491100000000@store1.noreply"
    _preparar_lote(monkeypatch, filas)

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 4
    assert len(_FakeRepo.schedules) == 4
    assert _SmtpFalso.conexiones == 0
    assert _SmtpFalso.enviados == []
    assert _FakeRepo.releases == []


@pytest.mark.asyncio
async def test_scheduler_persiste_sin_depender_de_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El outbox retoma el envio despues de reiniciar el worker."""
    now = datetime.now(timezone.utc)
    _preparar_lote(monkeypatch, _filas_vencidas(now, 5), caer_en_intento={2})

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 5
    assert len(_FakeRepo.schedules) == 5
    assert _SmtpFalso.intentos == 0
    assert _FakeRepo.releases == []


@pytest.mark.asyncio
async def test_outbox_schedule_survives_simulated_smtp_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El SMTP se consulta despues de confirmar la etapa y su fila de salida."""
    now = datetime.now(timezone.utc)
    _preparar_lote(monkeypatch, _filas_vencidas(now, 5), noop_muerto={1})

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 5
    assert _FakeRepo.releases == []
    assert len(_FakeRepo.schedules) == 5
    assert _SmtpFalso.intentos == 0


@pytest.mark.asyncio
async def test_scheduler_no_abre_conexion_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar_lote(
        monkeypatch,
        _filas_vencidas(now, 5),
        noop_muerto={1},
        rechazar_conexion={2},
    )

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 5
    assert _FakeRepo.releases == []
    assert len(_FakeRepo.schedules) == 5
    assert _SmtpFalso.intentos == 0
    assert _SmtpFalso.conexiones == 0


@pytest.mark.asyncio
async def test_lote_sin_envios_no_abre_ni_cierra_conexion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un lote sin filas enviables no escribe outbox ni abre el SMTP."""
    now = datetime.now(timezone.utc)
    filas = _filas_vencidas(now, 3)
    for fila in filas:
        fila[4].send_email_reminders = False
    _preparar_lote(monkeypatch, filas)

    salteados = await notification_tasks.process_due_appointment_reminders(now=now)
    assert salteados["skipped"] == 3

    _preparar_lote(monkeypatch, [])
    vacio = await notification_tasks.process_due_appointment_reminders(now=now)
    assert vacio["published"] == 0

    assert (_SmtpFalso.conexiones, _SmtpFalso.quits) == (0, 0)


@pytest.mark.asyncio
async def test_envio_suelto_abre_y_cierra_su_sesion_sin_reintentar_una_nueva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)
    _SmtpFalso.reset()
    assert await notification_tasks._send_email("a@example.com", "Asunto", "x")
    assert await notification_tasks._send_email("b@example.com", "Asunto", "x")
    assert (_SmtpFalso.conexiones, _SmtpFalso.logins, _SmtpFalso.quits) == (2, 2, 2)
    assert _SmtpFalso.noops == 0, "una conexion recien abierta no se sondea"

    # Una conexion recien abierta que se cae no se reintenta.
    _SmtpFalso.reset(caer_en_intento={0})
    assert not await notification_tasks._send_email("c@example.com", "Asunto", "x")
    assert _SmtpFalso.conexiones == 1
    assert _SmtpFalso.intentos == 1
