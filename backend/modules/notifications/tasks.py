"""
Notificaciones async compatibles con runtime serverless.

Usa Vercel Queues cuando hay token OIDC disponible y cae a SMTP directo
para confirmaciones cuando no es posible publicar en la cola.
"""
from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import structlog

from core.config import settings
from core.database import AsyncSessionFactory
from core.vercel_queue import ack_message, publish_json_message, queue_is_enabled, receive_json_messages

logger = structlog.get_logger()


async def _send_email(to: str, subject: str, body: str) -> bool:
    def _send() -> bool:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.EMAILS_FROM_EMAIL
        message["To"] = to
        message.set_content(body)

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
                smtp.send_message(message)
            return True
        except Exception as exc:  # pragma: no cover - depende de SMTP real
            logger.error("smtp_send_failed", to=to, error=str(exc))
            return False

    return await asyncio.to_thread(_send)


def _confirmation_subject(details: dict) -> str:
    return f"Turno confirmado - {details.get('service', '')}"


def _confirmation_body(details: dict) -> str:
    return (
        "Hola,\n\n"
        f"Tu turno para \"{details.get('service')}\" con {details.get('staff')} "
        "ha sido registrado correctamente.\n\n"
        f"Fecha y hora: {details.get('date')}\n\n"
        "Si necesitas cancelarlo, podes hacerlo desde la app hasta 2 horas antes.\n\n"
        "- El equipo de Shifty"
    )


def _reminder_subject(details: dict) -> str:
    return f"Recordatorio: turno manana - {details.get('service', '')}"


def _reminder_body(details: dict) -> str:
    return (
        "Hola,\n\n"
        f"Te recordamos que manana tenes turno para \"{details.get('service')}\" "
        f"con {details.get('staff')}.\n\n"
        f"Hora: {details.get('date')}\n\n"
        "Si necesitas cancelar, hacelo lo antes posible desde la app.\n\n"
        "- El equipo de Shifty"
    )


async def send_appointment_confirmation(email: str, details: dict) -> dict:
    logger.info("sending_confirmation_email", email=email, appointment=details.get("public_id"))
    success = await _send_email(email, _confirmation_subject(details), _confirmation_body(details))
    if not success:
        raise RuntimeError("SMTP send failed")
    logger.info("confirmation_email_sent", email=email)
    return {"status": "sent", "to": email}


async def send_appointment_reminder(email: str, details: dict) -> dict:
    logger.info("sending_reminder_email", email=email, appointment=details.get("public_id"))
    success = await _send_email(email, _reminder_subject(details), _reminder_body(details))
    if not success:
        raise RuntimeError("SMTP send failed")
    logger.info("reminder_email_sent", email=email)
    return {"status": "sent", "to": email}


async def enqueue_confirmation_email(
    *,
    email: str,
    details: dict,
    vercel_oidc_token: str | None,
) -> dict:
    payload = {"email": email, "details": details}
    if queue_is_enabled() and vercel_oidc_token:
        await publish_json_message(
            topic=settings.VERCEL_QUEUE_CONFIRMATION_TOPIC,
            payload=payload,
            oidc_token=vercel_oidc_token,
            idempotency_key=f"confirmation:{details.get('public_id')}",
        )
        drain_result = await drain_notification_queue(
            queue_kind="confirmations",
            vercel_oidc_token=vercel_oidc_token,
            max_messages=1,
        )
        return {
            "status": "queued_and_drained",
            "topic": settings.VERCEL_QUEUE_CONFIRMATION_TOPIC,
            "drain": drain_result,
        }

    if settings.VERCEL_QUEUE_CONFIRMATION_FALLBACK_SYNC:
        return await send_appointment_confirmation(email, details)

    return {"status": "skipped"}


async def enqueue_reminder_email(
    *,
    email: str,
    details: dict,
    vercel_oidc_token: str,
    delay_seconds: int = 0,
) -> dict:
    await publish_json_message(
        topic=settings.VERCEL_QUEUE_REMINDER_TOPIC,
        payload={"email": email, "details": details},
        oidc_token=vercel_oidc_token,
        delay_seconds=delay_seconds,
        retention_seconds=max(3600, delay_seconds + 3600),
        idempotency_key=f"reminder:{details.get('public_id')}:{details.get('date')}",
    )
    return {"status": "queued", "topic": settings.VERCEL_QUEUE_REMINDER_TOPIC}


async def schedule_24h_reminders(
    *,
    now: datetime,
    vercel_oidc_token: str | None,
) -> dict:
    if not queue_is_enabled():
        return {"status": "disabled", "reason": "VERCEL_QUEUE_REGION no configurado"}
    if not vercel_oidc_token:
        raise RuntimeError("No hay token OIDC de Vercel para publicar mensajes")

    window_start = now
    window_end = now + timedelta(hours=48)

    from modules.appointments.repository import AppointmentRepository

    published = 0
    async with AsyncSessionFactory() as db:
        repo = AppointmentRepository(db)
        rows = await repo.get_upcoming_for_reminders(
            starts_after=window_start,
            starts_before=window_end,
        )
        for appointment, service, staff, client in rows:
            reminder_at = appointment.starts_at.replace(tzinfo=timezone.utc) - timedelta(hours=24)
            delay_seconds = max(0, int((reminder_at - now).total_seconds()))
            await enqueue_reminder_email(
                email=client.email,
                details={
                    "public_id": appointment.public_id,
                    "service": service.name,
                    "staff": staff.display_name,
                    "date": appointment.starts_at.isoformat(),
                },
                vercel_oidc_token=vercel_oidc_token,
                delay_seconds=delay_seconds,
            )
            published += 1

    logger.info(
        "reminders_scheduled",
        published=published,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
    )
    drain_result = await drain_notification_queue(
        queue_kind="reminders",
        vercel_oidc_token=vercel_oidc_token,
    )
    return {
        "status": "scheduled",
        "published": published,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "drain": drain_result,
    }


async def drain_notification_queue(
    *,
    queue_kind: str,
    vercel_oidc_token: str | None,
    max_messages: int | None = None,
) -> dict:
    if not queue_is_enabled():
        return {"status": "disabled", "reason": "VERCEL_QUEUE_REGION no configurado"}
    if not vercel_oidc_token:
        raise RuntimeError("No hay token OIDC de Vercel para consumir la cola")

    if queue_kind == "confirmations":
        topic = settings.VERCEL_QUEUE_CONFIRMATION_TOPIC
        consumer = settings.VERCEL_QUEUE_CONFIRMATION_CONSUMER
        handler = send_appointment_confirmation
    elif queue_kind == "reminders":
        topic = settings.VERCEL_QUEUE_REMINDER_TOPIC
        consumer = settings.VERCEL_QUEUE_REMINDER_CONSUMER
        handler = send_appointment_reminder
    else:
        raise ValueError("queue_kind debe ser 'confirmations' o 'reminders'")

    drained = 0
    failed = 0
    messages = await receive_json_messages(
        topic=topic,
        consumer=consumer,
        oidc_token=vercel_oidc_token,
        max_messages=max_messages or settings.VERCEL_QUEUE_MAX_BATCH,
    )
    for message in messages:
        try:
            await handler(message.body["email"], message.body["details"])
            await ack_message(
                topic=topic,
                consumer=consumer,
                receipt_handle=message.receipt_handle,
                oidc_token=vercel_oidc_token,
            )
            drained += 1
        except Exception as exc:  # pragma: no cover - depende de SMTP/Queue real
            failed += 1
            logger.error(
                "queue_message_failed",
                topic=topic,
                message_id=message.message_id,
                delivery_count=message.delivery_count,
                error=str(exc),
            )

    return {
        "status": "drained",
        "queue": queue_kind,
        "drained": drained,
        "failed": failed,
        "received": len(messages),
    }
