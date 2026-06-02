"""
Tareas asíncronas de notificaciones (Celery).

Incluye:
  - send_appointment_confirmation: Email de confirmación al reservar.
  - send_appointment_reminder: Email recordatorio 24h antes.
  - send_24h_reminders: Tarea periódica (Celery Beat) que busca
    turnos del día siguiente y dispara send_appointment_reminder.
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import structlog

from core.celery_app import celery_app
from core.config import settings

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Helpers internos de SMTP
# ---------------------------------------------------------------------------

def _send_email(to: str, subject: str, body: str) -> bool:
    """
    Envía un email vía SMTP.
    Retorna True si tuvo éxito, False si falló (para que el caller decida reintentar).
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"]    = settings.EMAILS_FROM_EMAIL
    message["To"]      = to
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.send_message(message)
        return True
    except Exception as exc:
        logger.error("smtp_send_failed", to=to, error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Tarea: Confirmación de turno
# ---------------------------------------------------------------------------

@celery_app.task(name="send_appointment_confirmation", bind=True, max_retries=3)
def send_appointment_confirmation(self, email: str, details: dict) -> dict:
    """
    Envía el email de confirmación cuando se reserva un turno.
    Se ejecuta fuera de la transacción de base de datos (no bloquea el request).
    Implementa reintentos exponenciales en caso de falla SMTP.
    """
    logger.info(
        "sending_confirmation_email",
        email=email,
        appointment=details.get("public_id"),
    )

    subject = f"✅ Turno confirmado — {details.get('service', '')}"
    body = (
        f"Hola,\n\n"
        f"Tu turno para «{details.get('service')}» con {details.get('staff')} "
        f"ha sido registrado correctamente.\n\n"
        f"📅 Fecha y hora: {details.get('date')}\n\n"
        f"Si necesitás cancelarlo, podés hacerlo desde la app hasta 2 horas antes.\n\n"
        f"— El equipo de Shifty"
    )

    success = _send_email(email, subject, body)
    if not success:
        raise self.retry(
            exc=RuntimeError("SMTP send failed"),
            countdown=60 * (2 ** self.request.retries),  # backoff exponencial
        )

    logger.info("confirmation_email_sent", email=email)
    return {"status": "sent", "to": email}


# ---------------------------------------------------------------------------
# Tarea: Recordatorio 24h antes
# ---------------------------------------------------------------------------

@celery_app.task(name="send_appointment_reminder", bind=True, max_retries=3)
def send_appointment_reminder(self, email: str, details: dict) -> dict:
    """
    Envía un recordatorio 24h antes del turno.
    Disparado por la tarea periódica send_24h_reminders.
    """
    logger.info(
        "sending_reminder_email",
        email=email,
        appointment=details.get("public_id"),
    )

    subject = f"⏰ Recordatorio: turno mañana — {details.get('service', '')}"
    body = (
        f"Hola,\n\n"
        f"Te recordamos que mañana tenés turno para «{details.get('service')}» "
        f"con {details.get('staff')}.\n\n"
        f"📅 Hora: {details.get('date')}\n\n"
        f"Si necesitás cancelar, hacelo lo antes posible desde la app.\n\n"
        f"— El equipo de Shifty"
    )

    success = _send_email(email, subject, body)
    if not success:
        raise self.retry(
            exc=RuntimeError("SMTP send failed"),
            countdown=60 * (2 ** self.request.retries),
        )

    logger.info("reminder_email_sent", email=email)
    return {"status": "sent", "to": email}


# ---------------------------------------------------------------------------
# Tarea periódica: Disparador de recordatorios 24h
# (Registrada en Celery Beat Schedule en celery_app.py)
# ---------------------------------------------------------------------------

@celery_app.task(name="send_24h_reminders", bind=True)
def send_24h_reminders(self) -> dict:
    """
    Tarea periódica ejecutada cada hora por Celery Beat.

    Busca todos los turnos que empiezan en la ventana [ahora+23h, ahora+25h]
    y dispara un recordatorio para cada uno.

    La ventana de 2h evita duplicados si la tarea se ejecuta con pequeños desfases.
    """
    import asyncio
    from core.database import AsyncSessionFactory  # import local para evitar circular

    now   = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now + timedelta(hours=23)
    end   = now + timedelta(hours=25)

    logger.info("running_24h_reminders", window_start=start.isoformat(), window_end=end.isoformat())

    async def _run() -> int:
        from modules.appointments.repository import AppointmentRepository
        count = 0
        async with AsyncSessionFactory() as db:
            repo = AppointmentRepository(db)
            rows = await repo.get_upcoming_for_reminders(
                starts_after=start, starts_before=end
            )
            for appointment, service, staff, client in rows:
                send_appointment_reminder.delay(
                    email=client.email,
                    details={
                        "public_id": appointment.public_id,
                        "service":   service.name,
                        "staff":     staff.display_name,
                        "date":      appointment.starts_at.isoformat(),
                    },
                )
                count += 1
        return count

    dispatched = asyncio.run(_run())
    logger.info("reminders_dispatched", count=dispatched)
    return {"dispatched": dispatched}
