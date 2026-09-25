"""AUD2-B4-09 (2026-09-20): el aviso al dueño tambien pasa por is_deliverable_email.

Sintoma: los seis ``send_*_email`` al cliente abren con
``if not is_deliverable_email(email): return {"status": "skipped", ...}``.
``send_store_notification_email`` no tenia esa guarda y su proveedor
(``payments/jobs.py::_store_owner_mails``) solo filtra ``if email``. Un
administrador con un email tecnico o con una direccion rota generaba un rebote
por cada evento del outbox -que corre cada minuto-, que es exactamente lo que
ensucia la reputacion del remitente y el motivo por el que existe
``is_deliverable_email``.

La guarda va en el sink del aviso y no en el proveedor: asi cubre a cualquier
llamador nuevo sin que haya que acordarse.
"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest

import modules.notifications.tasks as tasks


class _SmtpProhibido:
    """Cualquier uso del SMTP en este camino es el defecto."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("se abrio una conexion SMTP para un email no entregable")


@pytest.mark.parametrize(
    "email",
    [
        "5491100000000@store1.noreply",
        "OTRO@Store2.NoReply",
        "",
        "sin-arroba",
    ],
)
@pytest.mark.asyncio
async def test_el_aviso_al_dueno_no_sale_a_un_email_no_entregable(
    monkeypatch: pytest.MonkeyPatch, email: str
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _SmtpProhibido)

    resultado = await tasks.send_store_notification_email(
        email=email, title="Sena acreditada", body="Turno appt-1"
    )

    assert resultado == {"status": "skipped", "reason": "no-deliverable"}


@pytest.mark.asyncio
async def test_un_email_real_del_dueno_sigue_recibiendo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enviados: list[tuple[str, str]] = []

    async def buzon(to: str, subject: str, body: str, smtp: Any = None) -> bool:
        enviados.append((to, subject))
        return True

    monkeypatch.setattr(tasks, "_send_email", buzon)

    resultado = await tasks.send_store_notification_email(
        email="duenio@example.com", title="Sena acreditada", body="Turno appt-1"
    )

    assert resultado == {"status": "sent"}
    assert enviados == [("duenio@example.com", "Shifty - Sena acreditada")]
