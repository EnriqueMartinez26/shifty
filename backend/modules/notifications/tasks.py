from __future__ import annotations

import asyncio
import httpx
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, cast

import structlog

from core.celery_app import celery_app
from core.worker_loop import run_in_worker_loop
from core.config import settings
from core.utils import ARGENTINA_TZ
from core.database import (
    AsyncSessionFactory,
    _apply_tenant_context,
    set_tenant_context,
)
from core.redis import get_redis

logger = structlog.get_logger()


def _mask_email(email: str | None) -> str:
    """Enmascara el email para no dejar PII de clientes en los logs."""
    if not email or "@" not in email:
        return "***"
    nombre, dominio = email.split("@", 1)
    visible = nombre[0] if nombre else ""
    return f"{visible}***@{dominio}"


def _header_safe(value: str) -> str:
    """Colapsa CR/LF/TAB a espacio: el Subject interpola nombres de servicio/
    tienda controlados por el usuario, y un CRLF ahi inyecta cabeceras (Bcc,
    asunto multiple). Se sanea en el sink para cubrir todos los callers."""
    return " ".join(value.split()) if value else value


async def _send_email(to: str, subject: str, body: str) -> bool:
    def _send() -> bool:
        message = EmailMessage()
        message["Subject"] = _header_safe(subject)
        message["From"] = settings.EMAILS_FROM_EMAIL
        message["To"] = _header_safe(to)
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


def is_deliverable_email(email: str | None) -> bool:
    """Descarta vacios y los emails tecnicos ``{tel}@store{id}.noreply``.

    El alta publica inventa un email tecnico cuando el cliente no deja uno:
    mandarle ahi rebota y ensucia la reputacion del remitente.
    """
    if not email or "@" not in email:
        return False
    return not email.lower().endswith(".noreply")


def format_local_datetime(value: Any) -> tuple[str, str]:
    """(fecha, hora) en hora argentina a partir de un ISO o datetime UTC.

    Los mails mostraban el ISO en UTC ("2026-09-11T14:00:00+00:00"); el
    cliente lee "11/09/2026" y "11:00".
    """
    if isinstance(value, datetime):
        instant = value
    else:
        try:
            instant = datetime.fromisoformat(str(value))
        except ValueError:
            return (str(value), "")
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local = instant.astimezone(ARGENTINA_TZ)
    return (local.strftime("%d/%m/%Y"), local.strftime("%H:%M"))


def build_client_details(
    appointment: Any, service: Any, staff: Any, store: Any | None
) -> dict[str, Any]:
    """Datos que necesitan todas las plantillas al cliente, en un solo lugar."""
    slug = getattr(store, "slug", None)
    base = settings.FRONTEND_URL.rstrip("/")
    return {
        "public_id": appointment.public_id,
        "client_name": getattr(appointment, "client_name", None) or "",
        "service": getattr(service, "name", ""),
        "staff": getattr(staff, "display_name", ""),
        "starts_at": appointment.starts_at.isoformat(),
        "store_name": getattr(store, "name", "") or "",
        "store_phone": getattr(store, "whatsapp_number", None) or "",
        "booking_url": f"{base}/b/{slug}" if slug else "",
    }


def _saludo(details: dict[str, Any]) -> str:
    nombre = str(details.get("client_name") or "").strip()
    return f"Hola {nombre}," if nombre else "Hola,"


def _contacto(details: dict[str, Any]) -> str:
    tienda = details.get("store_name") or "la tienda"
    telefono = details.get("store_phone")
    link = details.get("booking_url")
    partes = [f"Para cambios o cancelaciones, comunicate con {tienda}"]
    if telefono:
        partes.append(f"por WhatsApp al {telefono}")
    if link:
        partes.append(f"o entra en {link}")
    return " ".join(partes) + "."


def _cuando(details: dict[str, Any]) -> str:
    fecha, hora = format_local_datetime(details.get("starts_at") or details.get("date"))
    return f"{fecha} a las {hora} hs" if hora else fecha


def _registration_subject(details: dict[str, Any]) -> str:
    return f"Reserva registrada - {details.get('service', '')}"


def _registration_body(details: dict[str, Any]) -> str:
    return (
        f"{_saludo(details)}\n\n"
        f'Tu reserva para "{details.get("service")}" con {details.get("staff")} '
        f"quedo registrada para el {_cuando(details)}.\n\n"
        "Te vamos a avisar cuando este confirmada.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


def _confirmation_subject(details: dict[str, Any]) -> str:
    return f"Turno confirmado - {details.get('service', '')}"


def _confirmation_body(details: dict[str, Any]) -> str:
    return (
        f"{_saludo(details)}\n\n"
        f'Tu turno para "{details.get("service")}" con {details.get("staff")} '
        f"esta confirmado para el {_cuando(details)}.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


def _cancellation_subject(details: dict[str, Any]) -> str:
    return f"Turno cancelado - {details.get('service', '')}"


def _cancellation_body(details: dict[str, Any]) -> str:
    motivo = str(details.get("block_reason") or "").strip()
    linea_motivo = f" Motivo: {motivo}." if motivo else ""
    return (
        f"{_saludo(details)}\n\n"
        f'Lamentamos avisarte que tu turno para "{details.get("service")}" con '
        f"{details.get('staff')} del {_cuando(details)} fue cancelado por la "
        f"tienda.{linea_motivo}\n\n"
        "Podes elegir otro horario cuando quieras.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


def _reminder_subject(details: dict[str, Any]) -> str:
    return f"Recordatorio: turno manana - {details.get('service', '')}"


def _reminder_body(details: dict[str, Any]) -> str:
    return (
        f"{_saludo(details)}\n\n"
        f'Te recordamos que manana tenes turno para "{details.get("service")}" '
        f"con {details.get('staff')}, el {_cuando(details)}.\n\n"
        f"{_contacto(details)}\n\n"
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
    logger.info("confirmation_email_sent", email=_mask_email(email))
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
    logger.info("reminder_email_sent", email=_mask_email(email))
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


async def send_appointment_registration(
    email: str, details: dict[str, Any]
) -> dict[str, str]:
    logger.info(
        "sending_registration_email",
        email=_mask_email(email),
        appointment=details.get("public_id"),
    )
    success = await _send_email(
        email, _registration_subject(details), _registration_body(details)
    )
    if not success:
        raise RuntimeError("SMTP send failed")
    return {"status": "sent", "to": email}


async def enqueue_registration_email(
    *, email: str | None, details: dict[str, Any]
) -> dict[str, str]:
    """Mail "reserva registrada" al crear un turno pendiente. Nunca aborta."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        return await send_appointment_registration(email, details)
    except Exception as exc:
        logger.warning(
            "registration_email_dispatch_failed",
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}


async def enqueue_cancellation_email(
    *, email: str | None, details: dict[str, Any]
) -> dict[str, str]:
    """Mail "turno cancelado" (p.ej. por un bloqueo de agenda). Nunca aborta."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        success = await _send_email(
            email, _cancellation_subject(details), _cancellation_body(details)
        )
    except Exception as exc:
        logger.warning(
            "cancellation_email_dispatch_failed",
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}
    if not success:
        return {"status": "failed", "reason": "smtp"}
    return {"status": "sent", "to": email}


async def enqueue_confirmation_email(
    *, email: str | None, details: dict[str, Any]
) -> dict[str, str]:
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
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
        # Job global cross-tenant: sin request/tenant necesita el bypass RLS para
        # ver los turnos de TODAS las tiendas (shifty_app es NOBYPASSRLS). Las
        # filas quedan materializadas, asi que el resto del loop no toca la DB.
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            repo = AppointmentRepository(db)
            rows = await repo.get_upcoming_for_reminders(
                starts_after=window_start,
                starts_before=window_end,
            )
        finally:
            set_tenant_context(None, False)
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
        return run_in_worker_loop(_run())
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
