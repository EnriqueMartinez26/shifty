from celery import Celery
from celery.schedules import crontab
from core.config import settings

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
        "modules.payments.tasks",
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
    },
)
