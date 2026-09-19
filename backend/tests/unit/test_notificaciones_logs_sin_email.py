"""Los logs de notificaciones no llevan el email crudo del destinatario.

B4-07 (2026-09-18): ``modules/notifications/tasks.py`` define ``_mask_email``
"para no dejar PII de clientes en los logs" y lo usaba en la mitad de los
eventos; en otros cinco (``smtp_send_failed``, ``sending_confirmation_email``,
``sending_reminder_email``, ``confirmation_email_dispatch_failed`` y
``store_notification_email_failed``) iba el email completo a los logs de
produccion. ``sending_reminder_email`` desaparecio con X-08 (se borro
``send_appointment_reminder``, sin llamadores); el recordatorio vivo sale por
``notify_client_reminder``, que no loguea el email.

El segundo test deja constancia de que las guardas del sink siguen vivas en
el mismo camino: nunca a un email tecnico ``.noreply`` (is_deliverable_email)
y asunto sin CRLF.
"""

from __future__ import annotations

import smtplib
from collections.abc import MutableMapping
from email.message import EmailMessage
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from core.config import settings

import modules.notifications.tasks as tasks

EMAIL = "cliente.privado@example.com"
MASCARA = "c***@example.com"
DETAILS = {"public_id": "appt-logs", "service": "Consulta", "staff": "Ana"}


class _SmtpOk:
    enviados: list[EmailMessage] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_SmtpOk":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, *args: Any) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        _SmtpOk.enviados.append(message)


class _SmtpCaido:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise smtplib.SMTPConnectError(421, "servicio no disponible")


def _sin_email_crudo(eventos: list[MutableMapping[str, Any]]) -> None:
    for evento in eventos:
        assert EMAIL not in repr(evento), f"email crudo en el log: {evento}"


@pytest.mark.asyncio
async def test_eventos_de_envio_y_fallo_loguean_el_email_enmascarado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _SmtpOk)
    with capture_logs() as eventos:
        await tasks.send_appointment_confirmation(EMAIL, dict(DETAILS))
        # El recordatorio sale por notify_client_reminder (X-08 borro el
        # gemelo send_appointment_reminder): no loguea el email.
        await tasks.notify_client_reminder(
            phone=None, email=EMAIL, details=dict(DETAILS)
        )

    monkeypatch.setattr(smtplib, "SMTP", _SmtpCaido)
    with capture_logs() as eventos_fallo:
        assert await tasks._send_email(EMAIL, "Asunto", "cuerpo") is False
        resultado = await tasks.send_confirmation_email(
            email=EMAIL, details=dict(DETAILS)
        )
        assert resultado["status"] == "failed"

    async def _explota(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("smtp caido")

    monkeypatch.setattr(tasks, "_send_email", _explota)
    with capture_logs() as eventos_dueno:
        resultado = await tasks.send_store_notification_email(
            email=EMAIL, title="Pago acreditado"
        )
        assert resultado["status"] == "failed"

    todos = eventos + eventos_fallo + eventos_dueno
    por_nombre = {evento["event"]: evento for evento in todos}
    esperados = {
        "sending_confirmation_email": "email",
        "smtp_send_failed": "to",
        "confirmation_email_dispatch_failed": "email",
        "store_notification_email_failed": "email",
    }
    for nombre, clave in esperados.items():
        assert nombre in por_nombre, f"no se emitio {nombre}: {sorted(por_nombre)}"
        assert por_nombre[nombre][clave] == MASCARA, por_nombre[nombre]
    _sin_email_crudo(todos)


@pytest.mark.asyncio
async def test_guardas_del_sink_siguen_vivas(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_deliverable_email corta antes del SMTP y el asunto no lleva CRLF."""
    _SmtpOk.enviados = []
    monkeypatch.setattr(smtplib, "SMTP", _SmtpOk)

    saltado = await tasks.send_confirmation_email(
        email="5491100000000@store1.noreply", details=dict(DETAILS)
    )
    assert saltado == {"status": "skipped", "reason": "no-deliverable"}
    assert _SmtpOk.enviados == []

    hostil = dict(DETAILS, service="Corte\r\nBcc: victima@example.com")
    with capture_logs() as eventos:
        enviado = await tasks.send_confirmation_email(email=EMAIL, details=hostil)
    assert enviado["status"] == "sent"
    assert len(_SmtpOk.enviados) == 1
    asunto = str(_SmtpOk.enviados[0]["Subject"])
    assert "\r" not in asunto and "\n" not in asunto
    assert _SmtpOk.enviados[0]["Bcc"] is None
    _sin_email_crudo(eventos)


class _SmtpRechaza(_SmtpOk):
    """El servidor rechaza al destinatario: el texto del error trae la direccion."""

    def send_message(self, message: EmailMessage) -> None:
        raise smtplib.SMTPRecipientsRefused(
            {EMAIL: (550, f"5.1.1 <{EMAIL}>: Recipient address rejected".encode())}
        )


@pytest.mark.asyncio
async def test_el_error_smtp_no_filtra_la_direccion_rechazada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4-07, ajuste (2026-09-18): ``smtp_send_failed`` logueaba ``str(exc)`` y
    ``SMTPRecipientsRefused`` lleva la direccion (dos veces) en ese texto."""
    monkeypatch.setattr(smtplib, "SMTP", _SmtpRechaza)
    with capture_logs() as eventos:
        assert await tasks._send_email(EMAIL, "Asunto", "cuerpo") is False

    fallo = next(e for e in eventos if e["event"] == "smtp_send_failed")
    assert fallo["to"] == MASCARA
    assert fallo["error_type"] == "SMTPRecipientsRefused"
    # El diagnostico se conserva (codigo y motivo), sin la direccion cruda.
    assert "550" in fallo["error"] and "Recipient address rejected" in fallo["error"]
    assert MASCARA in fallo["error"]
    _sin_email_crudo(eventos)


@pytest.mark.parametrize(
    ("texto", "crudo"),
    [
        ("rechazado: ñandú@example.com", "ñandú@example.com"),
        ("rechazado 'comillas@example.com'", "comillas@example.com"),
        ('rechazado "dobles@example.com"', "dobles@example.com"),
        ("<josé.pérez@dominio-ñ.com.ar>: 550", "josé.pérez@dominio-ñ.com.ar"),
    ],
)
def test_el_texto_de_error_tapa_direcciones_no_ascii_y_entre_comillas(
    texto: str, crudo: str
) -> None:
    """Revision V-diff (2026-09-18): la expresion anterior solo tomaba ASCII."""
    enmascarado = tasks._mask_emails_in_text(texto)
    assert crudo not in enmascarado
    assert "***@" in enmascarado


class _RespuestaTwilio:
    status_code = 400
    text = (
        '{"code": 21211, "message": "The \'To\' number whatsapp:+5491155512345 '
        'is not a valid phone number.", "more_info": '
        '"https://www.twilio.com/docs/errors/21211", "status": 400}'
    )


class _TwilioRechaza:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_TwilioRechaza":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, *args: Any, **kwargs: Any) -> _RespuestaTwilio:
        return _RespuestaTwilio()


@pytest.mark.asyncio
async def test_el_rechazo_de_whatsapp_no_loguea_el_telefono(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision V-diff (2026-09-18): ``whatsapp_send_rejected`` logueaba
    ``resp.text`` y Twilio repite ahi el numero ``To`` completo."""
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC-test")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "token-test")
    monkeypatch.setattr(settings, "TWILIO_WHATSAPP_FROM", "whatsapp:+10000000000")
    monkeypatch.setattr(httpx, "AsyncClient", _TwilioRechaza)

    with capture_logs() as eventos:
        assert await tasks._send_whatsapp("+5491155512345", "hola") is False

    rechazo = next(e for e in eventos if e["event"] == "whatsapp_send_rejected")
    assert "5491155512345" not in repr(rechazo)
    assert "***2345" in rechazo["detail"]
    # El codigo de error de Twilio no es un telefono: se conserva.
    assert "21211" in rechazo["detail"]
