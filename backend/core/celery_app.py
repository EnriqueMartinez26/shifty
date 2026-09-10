import logging
import os
import tempfile

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, worker_init
from core.config import SETTINGS_BOOT_ERROR, settings
from core.model_registry import load_all_models
from core.observability import init_observability

logger = logging.getLogger(__name__)

# Los workers corren en procesos aparte: necesitan su propia inicializacion.
init_observability("worker")
# ...y su registro de modelos completo: las tasks importan Appointment pero
# no Staff, y las relaciones por nombre fallan al configurar los mappers.
load_all_models()


@worker_init.connect  # type: ignore[untyped-decorator]
@beat_init.connect  # type: ignore[untyped-decorator]
def _abort_if_settings_are_fallback(**_: object) -> None:
    """Ni el worker ni beat deben correr con la configuracion de respaldo.

    La API tolera un Settings() invalido para responder 503 con el detalle;
    un proceso de Celery con settings de respaldo apunta a una base
    inexistente y a un Redis en localhost, se declara "ready" y no procesa
    nada (beat ni siquiera puede encolar). Mejor morir a la vista: con
    restart:always queda en crash-loop con este mensaje en el log.
    SystemExit no es Exception, asi que el despachador de signals de Celery
    no lo traga.
    """
    if SETTINGS_BOOT_ERROR is None:
        return
    logger.critical(
        "Configuracion invalida, Celery no arranca: %s", SETTINGS_BOOT_ERROR
    )
    raise SystemExit(
        f"Configuracion invalida, Celery no arranca: {SETTINGS_BOOT_ERROR}"
    )


celery_app = Celery(
    "shifty",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND_URL or settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # Beat persiste "ultima corrida" en un archivo. Va al tmp del sistema:
    # dentro del directorio del codigo dejaba archivos de root en el repo
    # montado y en la imagen (usuario no-root) podia no ser escribible.
    # Perderlo en un reinicio es inocuo: los crontab se recalculan.
    beat_schedule_filename=os.path.join(
        tempfile.gettempdir(), "shifty-celerybeat-schedule"
    ),
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    task_acks_late=settings.CELERY_TASK_ACKS_LATE,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT_SECONDS,
    # Auto-descubrimiento de tareas en los módulos
    imports=[
        "modules.auth.tasks",
        "modules.payments.tasks",
        "modules.notifications.tasks",
        "modules.waitlist.tasks",
        "modules.billing.tasks",
    ],
    # ----------------------------------------------------------------
    # Celery Beat — Tareas periódicas
    # ----------------------------------------------------------------
    beat_schedule={
        # Ejecutar cada hora para detectar turnos del día siguiente
        "process-payment-outbox-every-minute": {
            "task": "process_payment_outbox",
            "schedule": crontab(),
        },
        "process-payment-webhook-inbox-every-minute": {
            "task": "process_payment_webhook_inbox",
            "schedule": crontab(),
        },
        "expire-unpaid-appointment-holds-every-minute": {
            "task": "expire_unpaid_appointments",
            "schedule": crontab(),
        },
        # Red de contencion por si un webhook de Mercado Pago nunca llego.
        "reconcile-pending-payments-every-5-minutes": {
            "task": "reconcile_pending_payments",
            "schedule": crontab(minute="*/5"),
        },
        "process-appointment-reminders-every-15-minutes": {
            "task": "process_appointment_reminders",
            "schedule": crontab(minute="*/15"),
        },
        # Ofertas de lista de espera vencidas: pasan a la siguiente persona.
        "process-waitlist-offers-every-5-minutes": {
            "task": "process_waitlist_offers",
            "schedule": crontab(minute="*/5"),
        },
        # Higiene de la tabla de sesiones: las expiradas/revocadas viejas se
        # purgan a diario (es material de credenciales, no un historico).
        "purge-expired-auth-sessions-daily": {
            "task": "purge_expired_auth_sessions",
            "schedule": crontab(minute=0, hour=4),
        },
        # Ciclo de vida de la suscripcion: aviso, vencimiento y suspension.
        # 09:00 UTC son las 06:00 en Argentina: el aviso llega temprano.
        "process-subscription-lifecycle-daily": {
            "task": "process_subscription_lifecycle",
            "schedule": crontab(minute=0, hour=9),
        },
    },
)
