from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "shifty",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Auto-descubrimiento de tareas en los módulos
    imports=[
        "modules.notifications.tasks",
    ],
    # ----------------------------------------------------------------
    # Celery Beat — Tareas periódicas
    # ----------------------------------------------------------------
    beat_schedule={
        # Ejecutar cada hora para detectar turnos del día siguiente
        "send-24h-reminders-hourly": {
            "task":     "send_24h_reminders",
            "schedule": crontab(minute=0),  # :00 de cada hora
        },
    },
)
