"""STARTTLS del SMTP verifica el certificado y el nombre del servidor.

PV-06 (auditoria de privacidad, 2026-09-24): ``SmtpSession._connect`` hacia
``smtp.starttls()`` sin contexto, y smtplib usa entonces
``ssl._create_stdlib_context()``: cifra pero NO verifica certificado ni
hostname. Alguien en el camino al proveedor de correo podia presentar
cualquier certificado y leer los mails (codigos OTP, datos de turnos) y la
clave del SMTP que viaja en el LOGIN.
"""

from __future__ import annotations

import ssl
from typing import Any

import pytest

import modules.notifications.tasks as tasks


class _SmtpEspia:
    instancias: list["_SmtpEspia"] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.starttls_kwargs: dict[str, Any] | None = None
        _SmtpEspia.instancias.append(self)

    def starttls(self, **kwargs: Any) -> None:
        self.starttls_kwargs = kwargs

    def login(self, *_args: Any) -> None:
        return None

    def close(self) -> None:
        return None


def test_starttls_usa_un_contexto_que_verifica(monkeypatch: pytest.MonkeyPatch) -> None:
    _SmtpEspia.instancias = []
    monkeypatch.setattr(tasks.smtplib, "SMTP", _SmtpEspia)

    tasks.SmtpSession()._connect()

    [smtp] = _SmtpEspia.instancias
    assert smtp.starttls_kwargs is not None
    contexto = smtp.starttls_kwargs.get("context")
    assert isinstance(contexto, ssl.SSLContext), "starttls sin contexto no verifica"
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True
