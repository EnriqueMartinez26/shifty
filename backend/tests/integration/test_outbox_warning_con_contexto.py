"""El warning de un mail del outbox que no salio conserva de que tienda y turno era.

2026-09-18, seguimiento S-04 de la revision de B2-01: al mover los envios
fuera de la transaccion del lote, los warnings viejos
(``store_notification_email_skipped`` con ``store_id``,
``client_confirmation_email_skipped`` con ``appointment_id``) se unificaron en
``outbox_email_skipped`` con solo ``error_type``. Un SMTP caido dejaba un log
que no decia a que tienda ni a que turno le falto el aviso.

Sin datos personales: ni el email ni el nombre del cliente van al log.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

import modules.payments.jobs as jobs
from modules.payments.model import OutboxMessage

EMAIL = "cliente-privado@example.com"


@pytest.mark.asyncio
async def test_el_warning_del_mail_fallido_lleva_tienda_y_turno_sin_datos_personales(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def smtp_caido(**kwargs: Any) -> None:
        raise ConnectionRefusedError("smtp caido")

    monkeypatch.setattr(jobs, "send_cancellation_email", smtp_caido)
    test_session.add(
        OutboxMessage(
            store_id="tienda-s04",
            event_type="appointment.cancelled_by_block",
            payload={
                "public_id": "turno-s04",
                "client_email": EMAIL,
                "client_name": "Nombre Privado",
            },
        )
    )
    await test_session.commit()

    with capture_logs() as eventos:
        resultado = await jobs.process_outbox_batch(test_session)

    assert resultado["processed"] == 1
    [aviso] = [e for e in eventos if e["event"] == "outbox_email_skipped"]
    assert aviso["store_id"] == "tienda-s04"
    assert aviso["appointment_id"] == "turno-s04"
    assert aviso["event_type"] == "appointment.cancelled_by_block"
    assert aviso["error_type"] == "ConnectionRefusedError"
    texto = repr(aviso)
    assert EMAIL not in texto and "Nombre Privado" not in texto
