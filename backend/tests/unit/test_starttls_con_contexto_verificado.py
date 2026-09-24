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

import modules.auth.service as auth_service


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


def test_el_reset_negocia_starttls_con_certificado_verificado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _SmtpQueRegistra.contextos = []
    # auth.service usa ``smtplib.SMTP`` por el modulo: se dobla ahi.
    monkeypatch.setattr(smtplib, "SMTP", _SmtpQueRegistra)

    auth_service.send_password_reset_email(
        "alguien@example.com", "https://shifty.local/reset?token=x"
    )

    assert len(_SmtpQueRegistra.contextos) == 1
    contexto = _SmtpQueRegistra.contextos[0]
    assert isinstance(contexto, ssl.SSLContext), (
        "starttls() sin context no verifica el certificado del servidor"
    )
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True
