"""B4-08 (2026-09-18): el lote de recordatorios reusa UNA conexion SMTP.

Sintoma: ``_send_email`` abria conexion + STARTTLS + LOGIN por cada mensaje;
el lote de recordatorios pagaba N handshakes en serie contra el time limit de
Celery (B4-02). Decision del coordinador: una sesion SMTP reutilizable a lo
largo del lote, conservando EXACTAMENTE el ciclo por turno de B4-02
(presupuesto -> reclamo -> envio -> liberacion ante fallo).

Revision V-diff (2026-09-18): la primera version reconectaba y REENVIABA si
el envio por una conexion reusada tiraba ``SMTPServerDisconnected``. smtplib
convierte en eso cualquier ``OSError`` al leer la respuesta, incluido el
timeout esperando el ``250`` del DATA: si el servidor ya habia aceptado el
mensaje, el cliente recibia el recordatorio dos veces. Ahora una conexion
reusada se sondea con ``NOOP`` ANTES de enviar (si esta muerta se reconecta)
y un fallo del envio en si nunca se reintenta: el turno se libera.
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
    # _preparar reemplaza el envio por un fake: aca se usa el real, que pasa
    # por is_deliverable_email y por la sesion SMTP del lote.
    monkeypatch.setattr(notification_tasks, "notify_client_reminder", _NOTIFY_REAL)
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)
    _SmtpFalso.reset(**fallas)


@pytest.mark.asyncio
async def test_n_recordatorios_usan_una_conexion_y_un_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    filas = _filas_vencidas(now, 5)
    # Un servicio con CRLF no inyecta cabeceras y un .noreply no recibe nada.
    filas[1][1].name = "Corte\r\nBcc: victima@example.com"
    filas[4][3].email = "5491100000000@store1.noreply"
    _preparar_lote(monkeypatch, filas)

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 4
    assert _SmtpFalso.conexiones == 1
    assert _SmtpFalso.logins == 1
    assert _SmtpFalso.quits == 1, "la sesion se cierra al terminar el lote"
    assert _SmtpFalso.noops == 3, "cada envio por una conexion reusada la sondea"
    assert len(_SmtpFalso.enviados) == 4
    for mensaje in _SmtpFalso.enviados:
        asunto = str(mensaje["Subject"])
        assert "\r" not in asunto and "\n" not in asunto
        assert mensaje["Bcc"] is None
        assert not str(mensaje["To"]).endswith(".noreply")
    assert _FakeRepo.releases == []


@pytest.mark.asyncio
async def test_timeout_durante_el_data_no_reenvia_y_libera_el_turno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) El tercer envio, por una conexion reusada, falla despues de
    empezar el DATA: un solo intento para ese mensaje y el turno se libera."""
    now = datetime.now(timezone.utc)
    _preparar_lote(monkeypatch, _filas_vencidas(now, 5), caer_en_intento={2})

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert _SmtpFalso.intentos == 5, "un intento por mensaje: nunca se reenvia"
    assert result["published"] == 4
    assert _FakeRepo.releases == [("appt-2", COLUMNA)]
    assert len(_FakeRepo.claims) - len(_FakeRepo.releases) == len(
        _SmtpFalso.enviados
    ), "reclamos que quedan == envios exitosos"
    # La conexion que fallo se descarta; el siguiente abre una nueva.
    assert _SmtpFalso.conexiones == 2


@pytest.mark.asyncio
async def test_conexion_muerta_detectada_por_noop_reconecta_y_envia_una_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(b) El NOOP antes del tercer envio encuentra la conexion caida: se
    reconecta y el mensaje sale una sola vez."""
    now = datetime.now(timezone.utc)
    _preparar_lote(monkeypatch, _filas_vencidas(now, 5), noop_muerto={1})

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 5
    assert _FakeRepo.releases == []
    assert _SmtpFalso.intentos == 5
    assert len(_SmtpFalso.enviados) == 5
    assert _SmtpFalso.conexiones == 2
    assert _SmtpFalso.logins == 2


@pytest.mark.asyncio
async def test_noop_muerto_y_reconexion_fallida_libera_solo_ese_turno(
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

    assert result["published"] == 4
    assert _FakeRepo.releases == [("appt-2", COLUMNA)]
    assert len(_FakeRepo.claims) - len(_FakeRepo.releases) == len(
        _SmtpFalso.enviados
    ), "reclamos que quedan == envios exitosos"
    assert _SmtpFalso.intentos == 4, "el turno sin conexion no intento enviar"
    assert _SmtpFalso.conexiones == 3


@pytest.mark.asyncio
async def test_lote_sin_envios_no_abre_ni_cierra_conexion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c) Regla 5 del cierre: un lote sin mails no toca el SMTP, asi que el
    QUIT nunca corre con el FOR UPDATE del lote sin commitear."""
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
