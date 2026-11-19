"""Los mails al cliente responden a la tienda, no a Shifty (#283, 2026-11-02).

Todos los mails al cliente salian de ``EMAILS_FROM_EMAIL`` sin ``Reply-To``:
cuando una clienta contestaba "no puedo ir" a una confirmacion, la respuesta
caia en el buzon de Shifty y la tienda nunca la veia. Decision de Mateo
(2026-11-02, ultimo comentario del issue): la tienda tiene un "Mail de
contacto" opcional (``stores.contact_email``) y los mails al cliente lo llevan
como ``Reply-To`` cuando esta cargado y es entregable. Sin contacto entregable
la cabecera no va. El OTP, la recuperacion de clave y los avisos al dueno no
la llevan nunca.

Se prueba el mensaje que de verdad arma el sink (``_build_message``),
reemplazando solo el envio por la red (``SmtpSession._send_sync``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from types import SimpleNamespace
from typing import Any

import pytest

import modules.auth.service as auth_service
import modules.notifications.tasks as tasks
from core.config import settings
from core.crypto import encrypt_secret

CLIENTA = "clienta@example.com"
CONTACTO = "hola@tienda-del-barrio.com"


@pytest.fixture
def enviados(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    capturados: list[EmailMessage] = []

    def _send_sync(self: tasks.SmtpSession, message: EmailMessage) -> None:
        capturados.append(message)

    monkeypatch.setattr(tasks.SmtpSession, "_send_sync", _send_sync)
    return capturados


def _detalles(contact_email: str | None) -> dict[str, Any]:
    """Los detalles que arma el camino real, con la tienda que corresponda."""
    turno = SimpleNamespace(
        public_id="turno-1",
        client_name="Carla",
        starts_at=datetime.now(timezone.utc) + timedelta(days=1),
        extra_services_snapshot=None,
        addons_snapshot=None,
        price_amount=None,
    )
    servicio = SimpleNamespace(name="Corte", public_id="srv-1")
    profesional = SimpleNamespace(display_name="Ana", kind="person", public_id="st-1")
    tienda = SimpleNamespace(
        name="Tienda del barrio",
        slug="tienda-del-barrio",
        whatsapp_number=None,
        contact_email=contact_email,
    )
    return tasks.build_client_details(turno, servicio, profesional, tienda)


Enviar = Callable[[dict[str, Any]], Awaitable[dict[str, str]]]


async def _enviar_reset_cifrado() -> None:
    encrypted_body = encrypt_secret("https://shifty.test/reset?t=x")
    assert encrypted_body is not None
    async with tasks.smtp_session() as smtp:
        resultado = await tasks.send_encrypted_outbox_email(
            smtp=smtp,
            to=CLIENTA,
            subject="Restablecer contraseña - Shifty",
            encrypted_body=encrypted_body,
        )
    assert resultado["status"] == "sent"


# Un caso por tipo de mail al cliente. El recordatorio va en sus dos etapas.
MAILS_AL_CLIENTE: dict[str, Enviar] = {
    "registration": lambda d: tasks.send_registration_email(email=CLIENTA, details=d),
    "confirmation": lambda d: tasks.send_confirmation_email(email=CLIENTA, details=d),
    "reminder_24h": lambda d: tasks.notify_client_reminder(
        email=CLIENTA, details={**d, "stage": "24h"}
    ),
    "reminder_2h": lambda d: tasks.notify_client_reminder(
        email=CLIENTA, details={**d, "stage": "2h"}
    ),
    "reschedule": lambda d: tasks.send_reschedule_email(email=CLIENTA, details=d),
    "cancellation": lambda d: tasks.send_cancellation_email(email=CLIENTA, details=d),
    "rebook": lambda d: tasks.send_rebook_email(email=CLIENTA, details=d),
    "waitlist_offer": lambda d: tasks.send_waitlist_offer_email(
        email=CLIENTA, details=d
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tipo", sorted(MAILS_AL_CLIENTE))
async def test_con_contacto_entregable_responde_a_la_tienda(
    tipo: str, enviados: list[EmailMessage]
) -> None:
    resultado = await MAILS_AL_CLIENTE[tipo](_detalles(CONTACTO))

    assert resultado["status"] == "sent"
    [mensaje] = enviados
    assert mensaje["To"] == CLIENTA
    assert mensaje["Reply-To"] == CONTACTO
    # El remitente sigue siendo Shifty: solo cambia a donde va la respuesta.
    assert mensaje["From"] == settings.EMAILS_FROM_EMAIL


@pytest.mark.asyncio
@pytest.mark.parametrize("tipo", sorted(MAILS_AL_CLIENTE))
@pytest.mark.parametrize(
    "contacto",
    [None, "", "5491155550000@store1.noreply"],
    ids=["sin-contacto", "vacio", "noreply"],
)
async def test_sin_contacto_entregable_no_lleva_reply_to(
    tipo: str, contacto: str | None, enviados: list[EmailMessage]
) -> None:
    resultado = await MAILS_AL_CLIENTE[tipo](_detalles(contacto))

    assert resultado["status"] == "sent"
    [mensaje] = enviados
    assert "Reply-To" not in mensaje


def test_sin_contacto_los_detalles_no_cambian() -> None:
    """Comportamiento previo: sin contacto, los detalles son los de siempre."""
    assert "reply_to" not in _detalles(None)
    assert _detalles(CONTACTO)["reply_to"] == CONTACTO


@pytest.mark.asyncio
async def test_un_contacto_con_crlf_no_inyecta_cabeceras(
    enviados: list[EmailMessage],
) -> None:
    """Regla 19: la API ya lo rechaza; el sink no confia en eso."""
    detalles = {**_detalles(None), "reply_to": f"{CONTACTO}\r\nBcc: espia@example.com"}

    resultado = await tasks.send_confirmation_email(email=CLIENTA, details=detalles)

    assert resultado["status"] == "sent"
    [mensaje] = enviados
    assert "Reply-To" not in mensaje
    assert "Bcc" not in mensaje
    assert "espia" not in mensaje.as_string()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contacto",
    [
        "hola@bücher.com",
        "ñandú@tienda.com",
        f"{CONTACTO}>",
        f"<{CONTACTO}",
        f'{CONTACTO}"',
        f"({CONTACTO})",
        f"[{CONTACTO}]",
        f"hola\\{CONTACTO}",
    ],
    ids=["dominio-unicode", "local-unicode", ">", "<", "comilla", "()", "[]", "\\"],
)
async def test_el_sink_solo_pone_una_direccion_ascii_simple(
    contacto: str, enviados: list[EmailMessage]
) -> None:
    """B1/A1 (verificacion, 2026-11-03): la API ya rechaza o normaliza estos
    valores; el sink tampoco los deja pasar. Un dominio Unicode salia como
    encoded-word dentro de la direccion (RFC 2047 en lugar del dominio).
    """
    detalles = {**_detalles(None), "reply_to": contacto}

    resultado = await tasks.send_confirmation_email(email=CLIENTA, details=detalles)

    assert resultado["status"] == "sent"
    [mensaje] = enviados
    assert "Reply-To" not in mensaje
    assert b"=?" not in mensaje.as_bytes(policy=SMTP)


@pytest.mark.asyncio
async def test_un_contacto_en_punycode_sale_tal_cual(
    enviados: list[EmailMessage],
) -> None:
    detalles = {**_detalles(None), "reply_to": "hola@xn--bcher-kva.com"}

    await tasks.send_confirmation_email(email=CLIENTA, details=detalles)

    [mensaje] = enviados
    crudo = mensaje.as_bytes(policy=SMTP)
    assert b"\r\nReply-To: hola@xn--bcher-kva.com\r\n" in crudo
    assert b"=?" not in crudo


@pytest.mark.asyncio
async def test_el_otp_nunca_lleva_reply_to(enviados: list[EmailMessage]) -> None:
    assert await tasks.deliver_otp_email(CLIENTA, "Tu codigo", "123456") == {
        "status": "sent"
    }
    assert await tasks.send_email(CLIENTA, "Tu codigo", "123456") is True

    assert len(enviados) == 2
    assert all("Reply-To" not in mensaje for mensaje in enviados)


@pytest.mark.asyncio
async def test_el_aviso_al_dueno_nunca_lleva_reply_to(
    enviados: list[EmailMessage],
) -> None:
    resultado = await tasks.send_store_notification_email(
        email="duena@example.com", title="Turno nuevo", body="Carla reservo"
    )

    assert resultado["status"] == "sent"
    [mensaje] = enviados
    assert "Reply-To" not in mensaje


@pytest.mark.parametrize(
    "enviar",
    [
        _enviar_reset_cifrado,
        lambda: auth_service.send_password_changed_email(CLIENTA),
    ],
    ids=["reset", "clave-cambiada"],
)
@pytest.mark.asyncio
async def test_la_recuperacion_de_clave_nunca_lleva_reply_to(
    enviar: Callable[[], Awaitable[None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    capturados: list[EmailMessage] = []

    async def _send_email(
        message: EmailMessage,
        *,
        event: str,
        priority: str,
        message_id: str,
    ) -> None:
        capturados.append(message)

    async def _send_outbox_email(
        to: str,
        subject: str,
        body: str,
        _smtp: tasks.SmtpSession | None = None,
        *,
        reply_to: str | None = None,
    ) -> bool:
        capturados.append(tasks._build_message(to, subject, body, reply_to))
        return True

    monkeypatch.setattr(auth_service, "_send_email", _send_email)
    monkeypatch.setattr(tasks, "_send_email", _send_outbox_email)
    await enviar()

    [mensaje] = capturados
    assert "Reply-To" not in mensaje
