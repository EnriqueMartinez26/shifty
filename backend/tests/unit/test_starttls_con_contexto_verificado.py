"""El mail de reset de clave negocia STARTTLS verificando el certificado.

2026-09-24, PV-06: ``smtp.starttls()`` sin ``context`` usa
``ssl._create_stdlib_context()``, que NO verifica certificado ni hostname: un
intermediario en la red podia presentar cualquier certificado y leer el link
de reset (que da control de la cuenta) y las credenciales SMTP del ``login``.
Con ``ssl.create_default_context()`` se exige ``CERT_REQUIRED`` y
``check_hostname``.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

import pytest

from core.mail_budget import MailReservation
from core.crypto import encrypt_secret
import modules.notifications.tasks as notification_tasks


class _SmtpQueRegistra:
    contextos: list[Any] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_SmtpQueRegistra":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        _SmtpQueRegistra.contextos.append(context)

    def login(self, *args: Any) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        return None


@pytest.mark.asyncio
async def test_el_reset_negocia_starttls_con_certificado_verificado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _SmtpQueRegistra.contextos = []
    # El mail durable sale por el sink SMTP compartido.
    monkeypatch.setattr(smtplib, "SMTP", _SmtpQueRegistra)

    async def admitido(**kwargs: Any) -> MailReservation:
        return MailReservation(
            decision="admitted",
            window_id="test",
            message_key="message",
            attempt_token="attempt",
            priority=kwargs["priority"],
            tracked=False,
        )

    async def finish(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(notification_tasks, "reserve_mail", admitido)
    monkeypatch.setattr(notification_tasks, "finish_mail", finish)

    encrypted_body = encrypt_secret("https://shifty.local/reset?token=x")
    assert encrypted_body is not None
    async with notification_tasks.smtp_session() as smtp:
        resultado = await notification_tasks.send_encrypted_outbox_email(
            smtp=smtp,
            to="alguien@example.com",
            subject="Restablecer contraseña - Shifty",
            encrypted_body=encrypted_body,
        )
    assert resultado["status"] == "sent"

    assert len(_SmtpQueRegistra.contextos) == 1
    contexto = _SmtpQueRegistra.contextos[0]
    assert isinstance(contexto, ssl.SSLContext), (
        "starttls() sin context no verifica el certificado del servidor"
    )
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True
