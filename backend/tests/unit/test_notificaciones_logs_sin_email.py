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
from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

import modules.notifications.tasks as tasks
from modules.notifications.reminders import STAGE_24H

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
        await tasks.notify_client_reminder(email=EMAIL, details=dict(DETAILS))

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


def test_el_enmascarado_de_telefonos_tapa_el_numero_y_deja_el_resto() -> None:
    """AUD2-B4-07 (2026-09-20) reemplaza al test del rechazo de Twilio.

    ``_mask_phones_in_text`` nacio para ``whatsapp_send_rejected``, que
    volcaba el ``resp.text`` donde Twilio repite el ``To`` completo. Ese
    camino ya no existe, pero el helper sigue vivo y sigue siendo la unica
    guarda entre un texto de error ajeno y el log, asi que se prueba solo.
    """
    texto = (
        '{"code": 21211, "message": "el numero +5491155512345 no es valido", '
        '"status": 400}'
    )
    enmascarado = tasks._mask_phones_in_text(texto)
    assert "5491155512345" not in enmascarado
    assert "***2345" in enmascarado
    # Un codigo de error no es un telefono: se conserva.
    assert "21211" in enmascarado


# ---------------------------------------------------------------------------
# AUD2-B4-08 (2026-09-20): los bordes que quedaron sin la guarda del sink.
# Tres logs volcaban ``str(exc)`` crudo y ``_build_message`` corria FUERA del
# ``try`` de ``SmtpSession.send``, asi que una excepcion del parser de
# cabeceras se propagaba con el asunto o la direccion en el texto. En el
# recordatorio eso ademas libera el reclamo: el mismo turno volvia a
# intentarlo cada 15 minutos hasta la hora del turno.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_fallo_al_armar_el_mensaje_queda_contenido_en_el_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explota(to: str, subject: str, body: str) -> EmailMessage:
        raise ValueError(f"cabecera invalida: <{to}> / {subject}")

    monkeypatch.setattr(tasks, "_build_message", explota)
    sesion = tasks.SmtpSession()

    with capture_logs() as eventos:
        assert await sesion.send(EMAIL, "Asunto", "cuerpo") is False

    fallo = next(e for e in eventos if e["event"] == "smtp_send_failed")
    assert fallo["error_type"] == "ValueError"
    _sin_email_crudo(eventos)


@pytest.mark.asyncio
async def test_el_fallo_de_la_confirmacion_no_vuelca_el_texto_crudo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explota(*args: Any, **kwargs: Any) -> dict[str, str]:
        raise RuntimeError(f"rechazado {EMAIL} desde +5491155512345")

    monkeypatch.setattr(tasks, "send_appointment_confirmation", explota)

    with capture_logs() as eventos:
        resultado = await tasks.send_confirmation_email(
            email=EMAIL, details=dict(DETAILS)
        )

    assert resultado["status"] == "failed"
    _sin_email_crudo(eventos)
    assert all("5491155512345" not in repr(e) for e in eventos)


@pytest.mark.asyncio
async def test_el_fallo_del_recordatorio_no_vuelca_el_texto_crudo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    liberados: list[str] = []

    class _Repo:
        async def claim_reminder(self, *args: Any) -> bool:
            return True

        async def release_reminder(self, appointment_id: str, columna: str) -> None:
            liberados.append(columna)

    async def explota(**kwargs: Any) -> dict[str, str]:
        raise RuntimeError(f"rechazado {EMAIL} desde +5491155512345")

    monkeypatch.setattr(tasks, "notify_client_reminder", explota)
    turno = SimpleNamespace(
        id="ap-1",
        public_id="appt-b408",
        client_email=EMAIL,
        starts_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        client_name="Ana",
    )
    fila = (
        turno,
        SimpleNamespace(name="Corte", public_id="srv-1"),
        SimpleNamespace(display_name="Ana", kind="person", public_id="stf-1"),
        SimpleNamespace(email=EMAIL),
        SimpleNamespace(name="Tienda", slug="tienda", whatsapp_number=None),
    )

    with capture_logs() as eventos:
        enviado = await tasks._dispatch_reminder(
            _Repo(), fila, STAGE_24H, datetime.now(timezone.utc)
        )

    assert enviado is False
    assert liberados == [STAGE_24H.column], "el reclamo se libera para reintentar"
    _sin_email_crudo(eventos)
    assert all("5491155512345" not in repr(e) for e in eventos)


@pytest.mark.asyncio
async def test_el_presupuesto_del_otp_no_loguea_la_url_de_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El cuarto ``str(exc)`` de AUD2-B4-08 estaba en ``modules/otp``.

    Un ``RedisError`` repite la URL de conexion en su texto, y esa URL lleva
    credenciales. Se loguea solo el tipo.
    """
    import modules.otp.service as otp_service
    from core.config import settings
    from redis.exceptions import RedisError

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)

    async def redis_caido() -> Any:
        raise RedisError("Error 111 connecting to redis://usuario:secreto@10.0.0.5")

    monkeypatch.setattr(otp_service, "get_redis", redis_caido)

    with capture_logs() as eventos:
        await otp_service._consume_budget("req", "store-1", "+5491155512345", 5)

    evento = next(e for e in eventos if e["event"] == "otp_budget_redis_unavailable")
    assert evento["error_type"] == "RedisError"
    assert "secreto" not in repr(evento)
