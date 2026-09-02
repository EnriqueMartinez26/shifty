from celery import Celery
from celery.schedules import crontab
from core.config import settings
from core.observability import init_observability

# Los workers corren en procesos aparte: necesitan su propia inicializacion.
init_observability("worker")

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
        # Higiene de la tabla de sesiones: las expiradas/revocadas viejas se
        # purgan a diario (es material de credenciales, no un historico).
        "purge-expired-auth-sessions-daily": {
            "task": "purge_expired_auth_sessions",
            "schedule": crontab(minute=0, hour=4),
        },
    },
)
