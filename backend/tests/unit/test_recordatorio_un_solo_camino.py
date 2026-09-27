"""El recordatorio al cliente sale por un solo camino: notify_client_reminder.

X-08 (2026-09-18, codigo muerto): ``send_appointment_reminder`` quedo sin
llamadores cuando el recordatorio paso a elegir canal (WhatsApp y despues
mail) en ``notify_client_reminder``. Ademas NO aplicaba
``is_deliverable_email``: era un atajo que, si alguien lo volvia a llamar,
mandaba al email tecnico ``.noreply``. Se borra; la guarda vive en
``notify_client_reminder`` (``test_reminder_stages_regresiones``
``::test_el_recordatorio_no_se_manda_al_email_tecnico_noreply``).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import httpx
import pytest

import modules.notifications.tasks as tasks
from core.config import settings


class _SalidaHttpProhibida(BaseException):
    """No hereda de ``Exception`` a proposito: ningun ``except`` la tapa."""


def test_no_queda_un_segundo_camino_de_recordatorio() -> None:
    assert not hasattr(tasks, "send_appointment_reminder")


def test_no_queda_el_camino_de_whatsapp() -> None:
    """AUD2-B4-07 (2026-09-20): el recordatorio probaba WhatsApp primero.

    Twilio responde 2xx al ENCOLAR, no al entregar: con TWILIO_* cargado, un
    numero sin WhatsApp daba 201, el codigo lo contaba como enviado, marcaba
    el reclamo y NO mandaba el mail. El cliente no recibia nada y no quedaba
    rastro. El producto difirio WhatsApp (solo email + wa.me manual), asi que
    el canal se saca en vez de dejarlo listo para activarse solo el dia que
    alguien cargue las credenciales.
    """
    assert not hasattr(tasks, "_send_whatsapp")
    assert "phone" not in inspect.signature(tasks.notify_client_reminder).parameters
    fuente = Path(str(tasks.__file__)).read_text(encoding="utf-8")
    # Solo el codigo: los comentarios explican por que se fue, y eso queda.
    assert "api.twilio.com" not in fuente
    assert "settings.TWILIO" not in fuente


@pytest.mark.asyncio
async def test_con_twilio_configurado_el_recordatorio_igual_sale_por_mail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cargar las credenciales no puede cambiar el canal por si solo."""
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC-test")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "token-test")
    monkeypatch.setattr(settings, "TWILIO_WHATSAPP_FROM", "whatsapp:+10000000000")

    def prohibido(*args: Any, **kwargs: Any) -> None:
        raise _SalidaHttpProhibida("el recordatorio intento salir por WhatsApp")

    monkeypatch.setattr(httpx, "AsyncClient", prohibido)

    enviados: list[str] = []

    async def buzon(to: str, subject: str, body: str, smtp: Any = None) -> bool:
        enviados.append(to)
        return True

    monkeypatch.setattr(tasks, "_send_email", buzon)

    resultado = await tasks.notify_client_reminder(
        email="cliente@example.com",
        details={"public_id": "appt-b407", "service": "Corte", "staff": "Ana"},
    )

    assert resultado["channel"] == "email"
    assert enviados == ["cliente@example.com"]


@pytest.mark.asyncio
async def test_el_unico_camino_no_manda_al_email_tecnico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enviados: list[str] = []

    async def buzon(to: str, subject: str, body: str, smtp: Any = None) -> bool:
        enviados.append(to)
        return True

    monkeypatch.setattr(tasks, "_send_email", buzon)

    resultado = await tasks.notify_client_reminder(
        email="5491100000000@store1.noreply",
        details={"public_id": "appt-x08", "service": "Corte", "staff": "Ana"},
    )
    assert resultado["status"] == "skipped"
    assert enviados == []
