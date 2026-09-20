from __future__ import annotations

import asyncio
import re
import smtplib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
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
from modules.notifications.reminders import (
    STAGE_2H,
    STAGE_24H,
    ReminderStage,
    due_stages,
)

logger = structlog.get_logger()

# B4-02 (2026-09-17): el lote de recordatorios corre bajo el time limit de
# Celery (120 s soft / 150 s hard, core/config.py) y cada recordatorio se
# reclama con commit ANTES de mandarse. Sin tope, con un SMTP lento el hard
# limit mataba el proceso a mitad del lote y los turnos ya reclamados quedaban
# marcados como enviados sin mail: la corrida siguiente los descartaba. Dos
# topes: filas por corrida (la query traia 5 objetos ORM por turno de 48 h de
# TODAS las tiendas) y un presupuesto de tiempo que se revisa ANTES de reclamar
# el siguiente. Lo que no entra queda con la marca en NULL y espera al tick
# siguiente (beat cada 15 minutos); el reclamo sigue siendo la exclusion.
#
# S-06 (2026-09-18): el resultado decia ``deferred`` y contaba solo las filas
# TRAIDAS que el presupuesto no alcanzo a revisar; lo que quedaba afuera del
# tope (o bloqueado por otra corrida, SKIP LOCKED) no aparecia. Saberlo exige
# otra consulta, asi que el numero se llama por lo que es: ``unexamined``
# (filas del lote sin revisar) y ``batch_full`` avisa que el lote vino lleno
# y puede haber mas turnos pendientes afuera del tope.
REMINDER_BATCH_LIMIT = 200
REMINDER_TIME_BUDGET_SECONDS = 90


def _mask_email(email: str | None) -> str:
    """Enmascara el email para no dejar PII de clientes en los logs."""
    if not email or "@" not in email:
        return "***"
    nombre, dominio = email.split("@", 1)
    visible = nombre[0] if nombre else ""
    return f"{visible}***@{dominio}"


# Direcciones dentro de un texto libre (p. ej. el ``str`` de
# ``SMTPRecipientsRefused``, que repite el destinatario rechazado). Cualquier
# token sin espacios ni ``<>"'`` a cada lado del ``@``: toma locales no ASCII
# y direcciones entre comillas; peca por tapar de mas, nunca de menos.
_EMAIL_IN_TEXT = re.compile(r"[^\s<>\"']+@[^\s<>\"']+")
# Telefonos dentro de un texto libre (Twilio repite el ``To`` en su error):
# 8 o mas digitos, con separadores habituales entre medio.
_PHONE_IN_TEXT = re.compile(r"\+?\d(?:[\s\-().]?\d){7,}")


def _mask_emails_in_text(text: str) -> str:
    """Enmascara cada direccion de un mensaje de error antes de loguearlo."""
    return _EMAIL_IN_TEXT.sub(lambda match: _mask_email(match.group(0)), text)


def _mask_phone(phone: str) -> str:
    """Deja solo los ultimos 4 digitos."""
    digits = re.sub(r"\D", "", phone)
    return f"***{digits[-4:]}"


def _mask_phones_in_text(text: str) -> str:
    """Enmascara cada telefono de un mensaje de error antes de loguearlo."""
    return _PHONE_IN_TEXT.sub(lambda match: _mask_phone(match.group(0)), text)


def _safe_error(exc: BaseException) -> str:
    """Texto de una excepcion ajena, listo para el log.

    AUD2-B4-08 (2026-09-20): tres logs volcaban ``str(exc)`` crudo. En el
    camino feliz esas excepciones eran siempre ``RuntimeError("SMTP send
    failed")``, asi que no filtraban nada: la garantia dependia de que
    ninguna excepcion con datos llegara ahi, no de una guarda. Ahora la
    guarda existe y tapa direcciones y telefonos, como el sink.
    """
    return _mask_emails_in_text(_mask_phones_in_text(str(exc)))


def _header_safe(value: str) -> str:
    """Colapsa CR/LF/TAB a espacio: el Subject interpola nombres de servicio/
    tienda controlados por el usuario, y un CRLF ahi inyecta cabeceras (Bcc,
    asunto multiple). Se sanea en el sink para cubrir todos los callers."""
    return " ".join(value.split()) if value else value


def _build_message(to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = _header_safe(subject)
    message["From"] = settings.EMAILS_FROM_EMAIL
    message["To"] = _header_safe(to)
    message.set_content(body)
    return message


# El servidor respondio con un error (destinatario rechazado, 5xx al DATA): la
# conversacion sigue coherente y la conexion se puede seguir usando.
_SMTP_REPLIES: tuple[type[Exception], ...] = (
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPResponseException,
)


class SmtpSession:
    """Una conexion SMTP (conexion + STARTTLS + LOGIN) para varios envios.

    B4-08 (2026-09-18): ``_send_email`` abria conexion, STARTTLS y LOGIN por
    cada mensaje, y el lote de recordatorios pagaba N handshakes en serie
    contra el time limit de Celery. Decision del coordinador: una sesion
    reutilizable a lo largo del lote (no una API de lista), para conservar el
    ciclo de B4-02 por turno (presupuesto -> reclamo -> envio -> liberacion).

    La conexion se abre en el primer envio, no al entrar: un lote sin mails
    no toca el SMTP, y el cierre nunca ocurre con el lote de la base sin
    commitear.

    Revision V-diff (2026-09-18): una conexion YA USADA se sondea con ``NOOP``
    antes de cada envio; si esta muerta se descarta y se abre otra. Un fallo
    del envio en si NUNCA se reintenta: smtplib convierte en
    ``SMTPServerDisconnected`` hasta el timeout esperando el ``250`` del
    DATA, y si el servidor ya habia aceptado el mensaje, reenviarlo le
    mandaba el recordatorio dos veces al cliente. ``send`` devuelve False y
    el llamador libera su reclamo como en B4-02.
    """

    def __init__(self) -> None:
        self._smtp: smtplib.SMTP | None = None

    def _connect(self) -> smtplib.SMTP:
        smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        try:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
        except Exception:
            smtp.close()
            raise
        return smtp

    def _discard(self) -> None:
        smtp, self._smtp = self._smtp, None
        if smtp is not None:
            try:
                smtp.close()
            except Exception:
                pass

    def _probe(self) -> None:
        """Descarta la conexion reusada si no responde al NOOP."""
        if self._smtp is None:
            return
        try:
            code, _ = self._smtp.noop()
        except Exception as exc:
            logger.warning("smtp_session_reconnect", error_type=type(exc).__name__)
            self._discard()
            return
        if code != 250:
            logger.warning("smtp_session_reconnect", noop_code=code)
            self._discard()

    def _send_sync(self, message: EmailMessage) -> None:
        self._probe()
        if self._smtp is None:
            self._smtp = self._connect()
        try:
            self._smtp.send_message(message)
        except Exception as exc:
            # Sin reintento: el DATA pudo haber llegado. Si el servidor
            # respondio con un error la conversacion sigue coherente; si no,
            # la conexion queda en estado incierto y se descarta.
            if not isinstance(exc, _SMTP_REPLIES):
                self._discard()
            raise

    async def send(self, to: str, subject: str, body: str) -> bool:
        try:
            # AUD2-B4-08: dentro del try. Afuera, un error del parser de
            # cabeceras se propagaba con el asunto o la direccion en el
            # texto, y en el recordatorio liberaba el reclamo, asi que el
            # mismo turno reintentaba cada 15 minutos hasta su hora.
            message = _build_message(to, subject, body)
            await asyncio.to_thread(self._send_sync, message)
            return True
        except Exception as exc:
            logger.error(
                "smtp_send_failed",
                to=_mask_email(to),
                error_type=type(exc).__name__,
                error=_safe_error(exc),
            )
            return False

    def close(self) -> None:
        smtp, self._smtp = self._smtp, None
        if smtp is None:
            return
        try:
            smtp.quit()
        except Exception:
            try:
                smtp.close()
            except Exception:
                pass


@asynccontextmanager
async def smtp_session() -> AsyncIterator[SmtpSession]:
    """Sesion SMTP para un lote; se cierra al salir aunque el lote falle."""
    session = SmtpSession()
    try:
        yield session
    finally:
        await asyncio.to_thread(session.close)


async def _send_email(
    to: str, subject: str, body: str, smtp: SmtpSession | None = None
) -> bool:
    """Sink unico de correo: con la sesion del lote la reusa, sin ella abre
    y cierra la suya.

    AUD2-B4-02 (2026-09-20): el consumidor del outbox despachaba su lista de
    mails post-commit abriendo conexion + STARTTLS + LOGIN por mensaje. Todos
    los ``send_*_email`` aceptan ahora la sesion del lote (B4-08), asi que un
    mail nuevo en el outbox no reintroduce el handshake por mail. El parametro
    vive aca y no en un helper aparte para que el sink -y el punto donde los
    tests lo reemplazan- siga siendo uno solo.
    """
    if smtp is not None:
        return await smtp.send(to, subject, body)
    async with smtp_session() as session:
        return await session.send(to, subject, body)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Envio suelto para otros modulos (p. ej. el OTP). Devuelve si salio.

    B4-12 (2026-09-18): ``otp`` importaba ``_send_email`` dentro de la
    funcion. Esta es la entrada publica; delega en ``_send_email`` al momento
    de la llamada (no es un alias ligado al importar), asi el sink SMTP sigue
    siendo uno solo y los tests que lo reemplazan cubren tambien este camino.
    """
    return await _send_email(to, subject, body)


async def deliver_otp_email(to: str, subject: str, body: str) -> dict[str, str]:
    """Cuerpo de la tarea ``send_otp_email``: manda por el sink unico.

    Vive aparte del wrapper de Celery para poder probarse con ``await``
    (``run_in_worker_loop`` se niega a anidarse en un loop activo).
    """
    delivered = await _send_email(to, subject, body)
    if not delivered:
        # El detalle ya lo logueo el sink, enmascarado. Aca solo queda que
        # este pedido de OTP no llego.
        logger.warning("otp_email_dispatch_failed", to=_mask_email(to))
    return {"status": "sent" if delivered else "failed"}


def _send_otp_email_task(to: str, subject: str, body: str) -> dict[str, str]:
    """Tarea de Celery: el mail del OTP sale del worker, no de la API.

    AUD2-B4-06 (2026-09-20): B4-01 saco el envio del camino sincronico con
    ``BackgroundTasks.add_task``, que no sale del proceso: el SMTP corria
    dentro de la misma llamada ASGI y un servidor colgado retenia el slot
    los 10 s del timeout por pedido, sin rastro durable si el proceso se
    reiniciaba entre la respuesta y el envio.

    Sin reintento (``max_retries=0``): un OTP que no salio se pide de nuevo,
    y reintentar un mail cuyo DATA pudo haber llegado lo duplica (misma
    razon que en ``SmtpSession``). La durabilidad la da el broker, no el
    reintento de la tarea.
    """
    return run_in_worker_loop(deliver_otp_email(to, subject, body))


# Anotada ``Any`` (y no por ``cast`` sobre el mismo nombre, como
# ``process_appointment_reminders``) porque a esta si se le llama ``.delay``:
# con el tipo de la funcion cruda mypy no ve el atributo que agrega Celery.
send_otp_email: Any = celery_app.task(name="send_otp_email", max_retries=0)(
    _send_otp_email_task
)


def enqueue_otp_email(to: str, subject: str, body: str) -> None:
    """Encola el mail del OTP. Nunca propaga.

    La respuesta del pedido de OTP es neutra por contrato (regla 20): no
    puede cambiar de forma ni de tiempo porque el broker este caido. Un
    fallo de encolado se trata como un fallo de envio: se loguea sin datos
    personales y el cliente vuelve a pedir el codigo.
    """
    try:
        send_otp_email.delay(to, subject, body)
    except Exception as exc:
        logger.warning("otp_email_enqueue_failed", error_type=type(exc).__name__)


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
        "staff_kind": getattr(staff, "kind", None) or "person",
        "starts_at": appointment.starts_at.isoformat(),
        "store_name": getattr(store, "name", "") or "",
        "store_phone": getattr(store, "whatsapp_number", None) or "",
        "booking_url": f"{base}/b/{slug}" if slug else "",
        # Deep-link "reserva de nuevo": mismo servicio y mismo profesional.
        "rebook_url": rebook_url(base, slug, service, staff),
    }


def rebook_url(base: str, slug: str | None, service: Any, staff: Any) -> str:
    if not slug:
        return ""
    params = []
    service_id = getattr(service, "public_id", None)
    # B4-11 (2026-09-18): sin fallback a ``staff.id``. Con el modelo real no
    # se alcanzaba (``Staff.public_id`` devuelve ``id``) y sugeria que un id
    # interno podia salir en el link al cliente. ``getattr`` porque el
    # profesional puede faltar (``waitlist/offers.py`` lo obtiene con db.get).
    staff_id = getattr(staff, "public_id", None)
    if service_id:
        params.append(f"service={service_id}")
    if staff_id:
        params.append(f"staff={staff_id}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"{base}/b/{slug}{query}"


def _con_quien(details: dict[str, Any]) -> str:
    """'con Ana' para una persona, 'en Cancha 2' para un recurso."""
    nexo = "en" if details.get("staff_kind") == "resource" else "con"
    return f"{nexo} {details.get('staff')}"


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
        f'Tu reserva para "{details.get("service")}" {_con_quien(details)} '
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
        f'Tu turno para "{details.get("service")}" {_con_quien(details)} '
        f"esta confirmado para el {_cuando(details)}.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


def _rescheduled_subject(details: dict[str, Any]) -> str:
    return f"Te movimos el turno - {details.get('service', '')}"


def _rescheduled_body(details: dict[str, Any]) -> str:
    return (
        f"{_saludo(details)}\n\n"
        f'La tienda movio tu turno de "{details.get("service")}" '
        f"{_con_quien(details)}: ahora es el {_cuando(details)}.\n\n"
        "Si ese horario no te sirve, avisanos.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


# B4-04 (2026-09-18): los ``send_*_email`` se llamaban ``enqueue_*_email`` y no
# encolaban nada: mandan SMTP ahora, en el camino del llamador (el llamador
# espera la respuesta del servidor de correo). Van siempre despues del commit
# y fuera de cualquier lock (regla 5; outbox: ``OfferResult.pending_email`` y
# los ``partial`` de payments/jobs). Quien necesite asincronia despacha una
# tarea de verdad; ``tests/architecture/test_enqueue_encola_de_verdad.py``
# impide que vuelva un ``enqueue_*`` que mande en linea.
async def send_reschedule_email(
    *, email: str | None, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    """Mail "te movimos el turno". Nunca aborta la reprogramacion."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        success = await _send_email(
            email, _rescheduled_subject(details), _rescheduled_body(details), smtp
        )
    except Exception as exc:
        logger.warning(
            "reschedule_email_dispatch_failed",
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}
    if not success:
        return {"status": "failed", "reason": "smtp"}
    return {"status": "sent", "to": email}


def _cancellation_subject(details: dict[str, Any]) -> str:
    return f"Turno cancelado - {details.get('service', '')}"


def _cancellation_body(details: dict[str, Any]) -> str:
    motivo = str(details.get("block_reason") or "").strip()
    linea_motivo = f" Motivo: {motivo}." if motivo else ""
    return (
        f"{_saludo(details)}\n\n"
        f'Lamentamos avisarte que tu turno para "{details.get("service")}" '
        f"{_con_quien(details)} del {_cuando(details)} fue cancelado por la "
        f"tienda.{linea_motivo}\n\n"
        "Podes elegir otro horario cuando quieras.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


def _reminder_subject(details: dict[str, Any]) -> str:
    fecha, hora = format_local_datetime(details.get("starts_at") or details.get("date"))
    if details.get("stage") == "2h":
        return f"Tu turno es a las {hora} - {details.get('service', '')}"
    return f"Recordatorio: tu turno del {fecha} - {details.get('service', '')}"


def _reminder_body(details: dict[str, Any]) -> str:
    # Sin "manana" ni "hoy": el job puede correr con atraso y la fecha explicita
    # nunca queda mal.
    if details.get("stage") == "2h":
        _, hora = format_local_datetime(details.get("starts_at") or details.get("date"))
        aviso = (
            f"Te recordamos que en un rato, a las {hora} hs, tenes turno para "
            f'"{details.get("service")}" {_con_quien(details)}.'
        )
    else:
        aviso = (
            f'Te recordamos que tenes turno para "{details.get("service")}" '
            f"{_con_quien(details)}, el {_cuando(details)}."
        )
    return (
        f"{_saludo(details)}\n\n"
        f"{aviso}\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


def _rebook_subject(details: dict[str, Any]) -> str:
    tienda = details.get("store_name") or "Shifty"
    return f"Gracias por tu visita - {tienda}"


def _rebook_body(details: dict[str, Any]) -> str:
    link = details.get("rebook_url") or details.get("booking_url") or ""
    tienda = details.get("store_name") or "la tienda"
    linea_link = f"\n\nReserva tu proximo turno en un toque: {link}" if link else ""
    return (
        f"{_saludo(details)}\n\n"
        f'Gracias por venir a {tienda}. Esperamos que "{details.get("service")}" '
        f"{_con_quien(details)} haya salido bien.{linea_link}\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


async def send_appointment_confirmation(
    email: str, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    logger.info(
        "sending_confirmation_email",
        email=_mask_email(email),
        appointment=details.get("public_id"),
    )
    success = await _send_email(
        email, _confirmation_subject(details), _confirmation_body(details), smtp
    )
    if not success:
        raise RuntimeError("SMTP send failed")
    logger.info("confirmation_email_sent", email=_mask_email(email))
    return {"status": "sent", "to": email}


async def notify_client_reminder(
    *,
    email: str | None,
    details: dict[str, Any],
    smtp: SmtpSession | None = None,
) -> dict[str, str]:
    """Avisa al cliente por mail. Unico canal del recordatorio.

    AUD2-B4-07 (2026-09-20): antes probaba WhatsApp (API de Twilio) primero y
    solo caia al mail si el envio devolvia False. Ese camino protegia a quien
    reserva sin dejar mail -el telefono es obligatorio y el mail no-, pero
    protegia mal: Twilio responde 2xx al ENCOLAR, no al entregar, asi que un
    numero sin WhatsApp daba 201, contaba como enviado, marcaba el reclamo y
    el mail no salia. El cliente no recibia nada y no quedaba rastro. Como el
    producto difirio WhatsApp (solo email + wa.me manual), el canal se saca:
    quien reserva sin mail hoy queda sin recordatorio, que es lo que ya
    pasaba de hecho porque TWILIO_* no esta configurado en produccion, y
    queda declarado en ``reminder_sin_canal`` en vez de escondido detras de
    un 201 de Twilio.

    ``smtp`` es la sesion del lote (B4-08); sin ella el mail sale suelto.
    """
    # El email tecnico {tel}@store{id}.noreply no recibe nada: mandarle ahi
    # rebota, ensucia la reputacion del remitente y, como el fallo libera el
    # reclamo, el job reintentaba cada 15 minutos hasta la hora del turno.
    if not is_deliverable_email(email):
        email = None

    if email:
        asunto = _reminder_subject(details)
        enviado = await _send_email(email, asunto, _reminder_body(details), smtp)
        if enviado:
            logger.info(
                "reminder_sent", canal="email", appointment=details.get("public_id")
            )
            return {"status": "sent", "channel": "email", "to": email}
        raise RuntimeError("SMTP send failed")

    logger.warning(
        "reminder_sin_canal",
        appointment=details.get("public_id"),
        motivo="el cliente no dejo un mail entregable",
    )
    return {"status": "skipped", "channel": "none"}


async def send_appointment_registration(
    email: str, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    logger.info(
        "sending_registration_email",
        email=_mask_email(email),
        appointment=details.get("public_id"),
    )
    success = await _send_email(
        email, _registration_subject(details), _registration_body(details), smtp
    )
    if not success:
        raise RuntimeError("SMTP send failed")
    return {"status": "sent", "to": email}


async def send_registration_email(
    *, email: str | None, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    """Mail "reserva registrada" al crear un turno pendiente. Nunca aborta."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        return await send_appointment_registration(email, details, smtp)
    except Exception as exc:
        logger.warning(
            "registration_email_dispatch_failed",
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}


async def send_cancellation_email(
    *, email: str | None, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    """Mail "turno cancelado" (p.ej. por un bloqueo de agenda). Nunca aborta."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        success = await _send_email(
            email, _cancellation_subject(details), _cancellation_body(details), smtp
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


async def send_rebook_email(
    *, email: str | None, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    """Mail "reserva tu proximo turno" al completar. Nunca aborta."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        success = await _send_email(
            email, _rebook_subject(details), _rebook_body(details), smtp
        )
    except Exception as exc:
        logger.warning(
            "rebook_email_dispatch_failed",
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}
    if not success:
        return {"status": "failed", "reason": "smtp"}
    return {"status": "sent", "to": email}


def _waitlist_offer_subject(details: dict[str, Any]) -> str:
    fecha, hora = format_local_datetime(details.get("starts_at"))
    return f"Se libero un turno el {fecha} a las {hora} - {details.get('service', '')}"


def _waitlist_offer_body(details: dict[str, Any]) -> str:
    minutos = details.get("offer_minutes") or 10
    link = details.get("offer_url") or details.get("booking_url") or ""
    linea_link = f"\n\nReservalo aca: {link}" if link else ""
    return (
        f"{_saludo(details)}\n\n"
        f'Se libero un turno para "{details.get("service")}" {_con_quien(details)} '
        f"el {_cuando(details)}, como pediste en la lista de espera.{linea_link}\n\n"
        f"Te lo reservamos durante {minutos} minutos; despues se lo ofrecemos a la "
        "siguiente persona de la lista.\n\n"
        f"{_contacto(details)}\n\n"
        "- El equipo de Shifty"
    )


async def send_waitlist_offer_email(
    *, email: str | None, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    """Mail "se libero un turno" a quien esta en lista de espera. Nunca aborta."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        success = await _send_email(
            email, _waitlist_offer_subject(details), _waitlist_offer_body(details), smtp
        )
    except Exception as exc:
        logger.warning(
            "waitlist_offer_email_dispatch_failed",
            entry=details.get("public_id"),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}
    if not success:
        return {"status": "failed", "reason": "smtp"}
    return {"status": "sent", "to": email}


async def send_confirmation_email(
    *, email: str | None, details: dict[str, Any], smtp: SmtpSession | None = None
) -> dict[str, str]:
    """Mail "turno confirmado". Nunca aborta la confirmacion."""
    if not is_deliverable_email(email):
        return {"status": "skipped", "reason": "no-deliverable"}
    assert email is not None
    try:
        return await send_appointment_confirmation(email, details, smtp)
    except Exception as exc:
        # Confirmations are operational side effects; they must never abort bookings.
        logger.warning(
            "confirmation_email_dispatch_failed",
            email=_mask_email(email),
            appointment=details.get("public_id"),
            error_type=type(exc).__name__,
            error=_safe_error(exc),
        )
        return {
            "status": "failed",
            "reason": type(exc).__name__,
        }


async def _dispatch_reminder(
    repo: Any,
    row: tuple[Any, Any, Any, Any, Any],
    stage: ReminderStage,
    now: datetime,
    smtp: SmtpSession | None = None,
) -> bool:
    """Reclama la marca durable y manda una etapa. Devuelve si se envio."""
    appointment, service, staff, client, store = row
    claimed = await repo.claim_reminder(appointment.id, stage.column, now)
    if not claimed:
        return False
    details = build_client_details(appointment, service, staff, store)
    details["stage"] = stage.name
    try:
        result = await notify_client_reminder(
            # AUD2-B4-01 (2026-09-20): el email de ESTA reserva, como los
            # otros cinco mails al cliente. El registro puede tener una
            # direccion vieja (o una que el titular nunca dio: sin OTP,
            # adopt_contact=False no la actualiza) y el recordatorio era el
            # unico aviso que la usaba. Se cae al registro si el turno no
            # trae email.
            email=getattr(appointment, "client_email", None)
            or getattr(client, "email", None),
            details=details,
            smtp=smtp,
        )
    except Exception as exc:
        # Se libera la marca para reintentar en la proxima corrida.
        await repo.release_reminder(appointment.id, stage.column)
        logger.warning(
            "appointment_reminder_dispatch_failed",
            appointment=appointment.public_id,
            stage=stage.name,
            error_type=type(exc).__name__,
            error=_safe_error(exc),
        )
        return False
    return result.get("status") == "sent"


@dataclass(frozen=True)
class _ReminderWindow:
    """Ventana de UNA etapa: el tope corta sobre filas que hay que mandar.

    AUD2-B4-04 (2026-09-20): antes habia una sola consulta de 48 h con el
    predicado "reminder_24h_sent_at IS NULL OR reminder_2h_sent_at IS NULL"
    -o sea, casi todos los turnos-, ordenada por ``starts_at`` y cortada en
    ``limit``. Los primeros del orden son los mas proximos, asi que con
    ``limit`` turnos empezando dentro de las proximas horas los que estaban a
    24 h no entraban nunca al lote; cuando entraban ya les faltaban menos de
    3 h y el piso de la etapa (``_PISO_24H``) los descartaba. El cliente
    dejaba de recibir el aviso de 24 h sin un solo error en el camino.
    """

    stage: ReminderStage
    starts_after: datetime
    starts_before: datetime


@dataclass
class _ReminderTotals:
    """Contadores compartidos por las ventanas de una corrida."""

    published: int = 0
    skipped: int = 0
    unexamined: int = 0
    batch_full: bool = False
    windows: list[str] = field(default_factory=list)


def _reminder_windows(now: datetime, lookahead_hours: int) -> list[_ReminderWindow]:
    """Una ventana por etapa, la mas urgente primero.

    Cada etapa se pide por separado para que su ``limit`` sea suyo y ninguna
    le coma el lugar a la otra. ``lookahead_hours`` queda solo como cota
    superior. Los extremos exactos los sigue decidiendo ``stage_is_due``: la
    ventana pide de mas (un minuto de margen) y nunca de menos.
    """
    tope = now + timedelta(hours=lookahead_hours)
    margen = timedelta(minutes=1)
    ventanas = []
    for stage in (STAGE_2H, STAGE_24H):
        starts_after = now + stage.floor
        starts_before = min(now + stage.lead + margen, tope)
        if starts_after < starts_before:
            ventanas.append(_ReminderWindow(stage, starts_after, starts_before))
    return ventanas


async def _process_reminder_window(
    repo: Any,
    ventana: _ReminderWindow,
    rows: list[tuple[Any, Any, Any, Any, Any]],
    now: datetime,
    smtp: SmtpSession,
    deadline: float,
    totales: _ReminderTotals,
) -> bool:
    """Manda la etapa de esta ventana. False si se agoto el presupuesto.

    El ciclo por turno de B4-02 no cambia: presupuesto -> reclamo -> envio ->
    liberacion ante fallo.
    """
    for index, row in enumerate(rows):
        if time.monotonic() >= deadline:
            # Presupuesto agotado: no se reclama ni uno mas. Los que quedan
            # siguen en NULL y salen en el proximo tick.
            totales.unexamined += len(rows) - index
            logger.warning(
                "reminders_time_budget_exhausted",
                stage=ventana.stage.name,
                unexamined=totales.unexamined,
                published=totales.published,
                budget_seconds=REMINDER_TIME_BUDGET_SECONDS,
            )
            return False
        appointment, _service, _staff, _client, store = row
        if ventana.stage not in due_stages(appointment, now):
            continue
        # Se cuenta salteado el turno al que le tocaba un aviso, no cada fila
        # que trajo la ventana.
        if not getattr(store, "send_email_reminders", True):
            totales.skipped += 1
            continue
        if await _dispatch_reminder(repo, row, ventana.stage, now, smtp):
            totales.published += 1
    return True


async def process_due_appointment_reminders(
    *,
    now: datetime | None = None,
    lookahead_hours: int = 48,
    limit: int = REMINDER_BATCH_LIMIT,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    # Reloj monotonico y no ``now``: ``now`` es la hora logica del lote
    # (inyectable en tests) y el presupuesto es tiempo real de proceso.
    deadline = time.monotonic() + REMINDER_TIME_BUDGET_SECONDS

    from modules.appointments.repository import AppointmentRepository

    totales = _ReminderTotals()
    async with AsyncSessionFactory() as db:
        # Job global cross-tenant: sin request/tenant necesita el bypass RLS para
        # ver y reclamar los turnos de TODAS las tiendas (shifty_app es
        # NOBYPASSRLS). El contexto se mantiene durante toda la sesion porque
        # los reclamos commitean y TenantSession lo reaplica.
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            repo = AppointmentRepository(db)
            # B4-08: una sola conexion SMTP para todo el lote.
            async with smtp_session() as smtp:
                for ventana in _reminder_windows(now, lookahead_hours):
                    rows = await repo.get_upcoming_for_reminders(
                        starts_after=ventana.starts_after,
                        starts_before=ventana.starts_before,
                        limit=limit,
                    )
                    totales.windows.append(ventana.stage.name)
                    # Ventana llena: puede haber mas turnos afuera del tope.
                    totales.batch_full = totales.batch_full or len(rows) >= limit
                    if not await _process_reminder_window(
                        repo, ventana, rows, now, smtp, deadline, totales
                    ):
                        break
        finally:
            set_tenant_context(None, False)

    window_start = now
    window_end = now + timedelta(hours=lookahead_hours)
    logger.info(
        "reminders_processed",
        published=totales.published,
        skipped=totales.skipped,
        unexamined=totales.unexamined,
        batch_full=totales.batch_full,
        stages=totales.windows,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
    )
    return {
        "status": "processed",
        "published": totales.published,
        "skipped": totales.skipped,
        "unexamined": totales.unexamined,
        "batch_full": totales.batch_full,
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
    *,
    email: str,
    title: str,
    body: str | None = None,
    smtp: SmtpSession | None = None,
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
            email, f"Shifty - {title}", _store_notification_body(title, body), smtp
        )
        return {"status": "sent" if delivered else "failed"}
    except Exception as exc:
        logger.warning(
            "store_notification_email_failed",
            email=_mask_email(email),
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": type(exc).__name__}
