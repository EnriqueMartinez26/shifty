from __future__ import annotations

import asyncio
import httpx
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, cast

import structlog

from core.celery_app import celery_app
from core.config import settings
from core.database import AsyncSessionFactory
from core.redis import get_redis

logger = structlog.get_logger()


async def _send_email(to: str, subject: str, body: str) -> bool:
    def _send() -> bool:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.EMAILS_FROM_EMAIL
        message["To"] = to
        message.set_content(body)

        try:
            with smtplib.SMTP(
                settings.SMTP_HOST, settings.SMTP_PORT, timeout=10
            ) as smtp:
                smtp.starttls()
                smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
                smtp.send_message(message)
            return True
        except Exception as exc:  # pragma: no cover - depende de SMTP real
            logger.error("smtp_send_failed", to=to, error=str(exc))
            return False

    return await asyncio.to_thread(_send)


def _confirmation_subject(details: dict[str, Any]) -> str:
    return f"Turno confirmado - {details.get('service', '')}"


def _confirmation_body(details: dict[str, Any]) -> str:
    return (
        "Hola,\n\n"
        f'Tu turno para "{details.get("service")}" con {details.get("staff")} '
        "ha sido registrado correctamente.\n\n"
        f"Fecha y hora: {details.get('date')}\n\n"
        "Si necesitas cancelarlo, podes hacerlo desde la app hasta 2 horas antes.\n\n"
        "- El equipo de Shifty"
    )


def _reminder_subject(details: dict[str, Any]) -> str:
    return f"Recordatorio: turno manana - {details.get('service', '')}"


def _reminder_body(details: dict[str, Any]) -> str:
    return (
        "Hola,\n\n"
        f'Te recordamos que manana tenes turno para "{details.get("service")}" '
        f"con {details.get('staff')}.\n\n"
        f"Hora: {details.get('date')}\n\n"
        "Si necesitas cancelar, hacelo lo antes posible desde la app.\n\n"
        "- El equipo de Shifty"
    )


async def send_appointment_confirmation(
    email: str, details: dict[str, Any]
) -> dict[str, str]:
    logger.info(
        "sending_confirmation_email", email=email, appointment=details.get("public_id")
    )
    success = await _send_email(
        email, _confirmation_subject(details), _confirmation_body(details)
    )
    if not success:
        raise RuntimeError("SMTP send failed")
    logger.info("confirmation_email_sent", email=email)
    return {"status": "sent", "to": email}


async def send_appointment_reminder(
    email: str, details: dict[str, Any]
) -> dict[str, str]:
    logger.info(
        "sending_reminder_email", email=email, appointment=details.get("public_id")
    )
    success = await _send_email(
        email, _reminder_subject(details), _reminder_body(details)
    )
    if not success:
        raise RuntimeError("SMTP send failed")
    logger.info("reminder_email_sent", email=email)
    return {"status": "sent", "to": email}


async def _send_whatsapp(to_phone: str, body: str) -> bool:
    """Envia un WhatsApp por la API REST de Twilio.

    Se usa httpx (ya es dependencia) en vez del SDK para no sumar un paquete
    por tres lineas de HTTP. Si Twilio no esta configurado devuelve False sin
    romper: el llamador cae al mail.
    """
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN
    origen = settings.TWILIO_WHATSAPP_FROM
    if not (sid and token and origen):
        return False

    destino = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"To": destino, "From": origen, "Body": body},
            )
    except httpx.RequestError as exc:
        logger.warning("whatsapp_send_failed", error=str(exc))
        return False

    if resp.status_code >= 400:
        logger.warning(
            "whatsapp_send_rejected",
            status=resp.status_code,
            detail=resp.text[:200],
        )
        return False
    return True


async def notify_client_reminder(
    *, phone: str | None, email: str | None, details: dict[str, Any]
) -> dict[str, str]:
    """Avisa al cliente por el mejor canal disponible.

    WhatsApp primero: el telefono es obligatorio al reservar y el mail no, asi
    que antes quien reservaba sin mail no recibia ningun recordatorio. Si
    WhatsApp no esta configurado o falla, se cae al mail.
    """
    cuerpo = _reminder_body(details)

    if phone and await _send_whatsapp(phone, cuerpo):
        logger.info(
            "reminder_sent", canal="whatsapp", appointment=details.get("public_id")
        )
        return {"status": "sent", "channel": "whatsapp", "to": phone}

    if email:
        if await _send_email(email, _reminder_subject(details), cuerpo):
            logger.info(
                "reminder_sent", canal="email", appointment=details.get("public_id")
            )
            return {"status": "sent", "channel": "email", "to": email}
        raise RuntimeError("SMTP send failed")

    logger.warning(
        "reminder_sin_canal",
        appointment=details.get("public_id"),
        motivo="el cliente no tiene mail y WhatsApp no esta configurado",
    )
    return {"status": "skipped", "channel": "none"}


async def enqueue_confirmation_email(
    *, email: str, details: dict[str, Any]
) -> dict[str, str]:
    try:
        return await send_appointment_confirmation(email, details)
    except Exception as exc:
        # Confirmations are operational side effects; they must never abort bookings.
        logger.warning(
            "confirmation_email_dispatch_failed",
            email=email,
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {
            "status": "failed",
            "reason": type(exc).__name__,
        }


async def process_due_appointment_reminders(
    *, now: datetime | None = None, lookahead_hours: int = 48
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    window_start = now
    window_end = now + timedelta(hours=lookahead_hours)

    from modules.appointments.repository import AppointmentRepository

    published = 0
    skipped = 0
    async with AsyncSessionFactory() as db:
        repo = AppointmentRepository(db)
        rows = await repo.get_upcoming_for_reminders(
            starts_after=window_start,
            starts_before=window_end,
        )
        redis = await get_redis()
        for appointment, service, staff, client, store in rows:
            if not getattr(store, "send_email_reminders", True):
                skipped += 1
                continue

            starts_at = appointment.starts_at
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            else:
                starts_at = starts_at.astimezone(timezone.utc)

            reminder_at = starts_at - timedelta(hours=24)
            if reminder_at > now:
                continue

            reminder_key = f"reminder:sent:{appointment.public_id}"
            claimed = await redis.set(
                reminder_key,
                "1",
                nx=True,
                ex=60 * 60 * 24 * 7,
            )
            if not claimed:
                continue

            try:
                await notify_client_reminder(
                    phone=getattr(client, "phone", None),
                    email=client.email,
                    details={
                        "public_id": appointment.public_id,
                        "service": service.name,
                        "staff": staff.display_name,
                        "date": starts_at.isoformat(),
                    },
                )
                published += 1
            except Exception as exc:  # pragma: no cover - depende de SMTP real
                await redis.delete(reminder_key)
                logger.warning(
                    "appointment_reminder_dispatch_failed",
                    appointment=appointment.public_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

    logger.info(
        "reminders_processed",
        published=published,
        skipped=skipped,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
    )
    return {
        "status": "processed",
        "published": published,
        "skipped": skipped,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }


def process_appointment_reminders(
    self: Any, lookahead_hours: int = 48
) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        result = await process_due_appointment_reminders(
            now=datetime.now(timezone.utc),
            lookahead_hours=lookahead_hours,
        )
        return {
            "published": int(result["published"]),
            "skipped": int(result["skipped"]),
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


process_appointment_reminders = cast(
    Any,
    celery_app.task(name="process_appointment_reminders", bind=True, max_retries=3)(
        process_appointment_reminders
    ),
)


def _store_notification_body(title: str, body: str | None) -> str:
    lines = [title]
    if body:
        lines.append("")
        lines.append(body)
    lines.append("")
    lines.append("Ingresá a Shifty para verlo en tu panel.")
    return "\n".join(lines)


async def send_store_notification_email(
    *, email: str, title: str, body: str | None = None
) -> dict[str, str]:
    """Avisa por mail al dueño de la tienda.

    La campanita del panel solo sirve si el dueño entra. Un turno que espera
    confirmacion manual o una seña acreditada necesitan llegarle aunque no
    tenga Shifty abierto.

    Nunca propaga errores: es un efecto secundario operativo y no puede
    abortar el procesamiento del outbox.
    """
    try:
        delivered = await _send_email(
            email, f"Shifty - {title}", _store_notification_body(title, body)
        )
        return {"status": "sent" if delivered else "failed"}
    except Exception as exc:
        logger.warning(
            "store_notification_email_failed",
            email=email,
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}
