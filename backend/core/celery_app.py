import logging
from pathlib import Path

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, heartbeat_sent, worker_init
from core.config import SETTINGS_BOOT_ERROR, settings
from core.database import assert_rls_capable_role, engine
from core.model_registry import load_all_models
from core.observability import init_observability
from core.worker_loop import run_in_worker_loop

logger = logging.getLogger(__name__)

# Registro de modelos completo: las tasks importan Appointment pero no Staff, y
# las relaciones por nombre fallan al configurar los mappers. Queda a nivel de
# modulo porque tiene que estar listo antes de la primera tarea y no depende de
# que el proceso sea un worker (lo cubre test_model_registry).
load_all_models()


@worker_init.connect  # type: ignore[untyped-decorator]
@beat_init.connect  # type: ignore[untyped-decorator]
def _start_worker_process(**_: object) -> None:
    """Arranque de un proceso de Celery (worker o beat), y SOLO de ellos.

    Sentry no se puede inicializar en el cuerpo de este modulo: el proceso de
    la API lo importa sin querer, por la cadena `main` ->
    `modules.appointment_blocks.router` -> `...service` ->
    `modules.notifications.tasks` -> `core.celery_app`, 128 lineas ANTES de su
    propio `init_observability("api")`. Como el init tiene un guard global
    `_initialized`, el de la API retornaba sin hacer nada y TODOS sus eventos
    salian etiquetados `component="worker"`: la unica senal para separar un
    request roto de un job roto respondia siempre lo mismo (AUD2-B7-04,
    2026-09-20).

    La configuracion se valida ANTES de Sentry: el DSN sale de esos mismos
    settings, y con settings de respaldo el proceso tiene que morir igual
    (regla 21). El chequeo del rol va al final, porque es el unico que abre una
    conexion a la base.
    """
    _abort_if_settings_are_fallback()
    init_observability("worker")
    _abort_if_role_can_bypass_rls()


# Archivo de latido del worker (F0-18, decision 7). El healthcheck de compose
# de los dos workers mira su antiguedad (obsoleto a los 120 s). Vive en
# /var/lib/shifty, que el Dockerfile crea con dueno appuser.
WORKER_HEARTBEAT_FILE = "/var/lib/shifty/worker-heartbeat"


@heartbeat_sent.connect  # type: ignore[untyped-decorator]
def _touch_worker_heartbeat(**_: object) -> None:
    """Renueva el archivo de latido en cada latido de eventos del worker.

    Reemplaza a `celery inspect ping` como healthcheck: ese comando levantaba
    un Python completo (~120 MB) dentro del cgroup del worker cada minuto. El
    latido lo emite el consumidor (bootstep Heart, cada 2 s) sobre su conexion
    al broker: si la conexion se cae o el loop del consumidor se traba, deja
    de latir y el archivo envejece. Asi el healthcheck sigue probando que el
    worker CONSUME, no solo que el proceso existe (AUD2-C-09).

    Nunca levanta: un disco que no acepta la escritura se ve como unhealthy en
    el healthcheck, no como un consumidor muerto.
    """
    try:
        Path(WORKER_HEARTBEAT_FILE).touch()
    except OSError:
        logger.debug("worker_heartbeat_touch_failed", exc_info=True)


def _abort_if_role_can_bypass_rls() -> None:
    """El worker y beat tampoco pueden correr con un rol que saltea RLS.

    Los tres procesos usan la MISMA ``DATABASE_URL``, del mismo bloque de
    compose que ``MIGRATION_DATABASE_URL``: confundirlas es un typo de una
    palabra. Con el chequeo solo en el lifespan de FastAPI, la API moria
    ruidosamente y Celery seguia trabajando sin aislamiento multi-tenant, en
    silencio, sobre turnos, pagos y outbox de TODAS las tiendas (AUD2-B7-08,
    2026-09-20).

    Cualquier fallo se traduce a ``SystemExit``: el despachador de signals de
    Celery se traga las ``Exception``, asi que un rol equivocado o una base que
    no responde dejarian al proceso "ready" sin haber verificado nada. Cuesta
    una conexion durante ``worker_init``, que es el precio de la garantia que
    CLAUDE.md §2 dice tener.

    Y el pool se desecha ANTES de devolver. ``worker_init`` corre en el proceso
    PADRE de prefork (``WorkController.setup_instance``), antes del fork: la
    conexion que abre el chequeo vuelve al QueuePool del engine global y cada
    hijo hereda ese registro -mismo descriptor, atado al event loop del
    padre-, asi que la primera tarea que la saque del pool muere con "attached
    to a different loop" / "Event loop is closed". Es el bug que documenta
    ``core/worker_loop.py`` y que ese modulo existe para evitar; ``pool_pre_ping``
    no lo detecta porque el ping corre sobre la misma conexion prestada. Beat no
    forkea, pero desechar un pool recien usado no le cuesta nada.
    """
    try:
        run_in_worker_loop(assert_rls_capable_role(engine))
    except SystemExit:
        raise
    except BaseException as exc:
        logger.critical("Celery no arranca, no se pudo verificar el rol: %s", exc)
        raise SystemExit(f"Celery no arranca, no se pudo verificar el rol: {exc}")
    finally:
        _dispose_pool_before_fork()


def _dispose_pool_before_fork() -> None:
    """Deja el pool del padre vacio; un fallo al cerrarlo no tapa el motivo.

    Si esto levantara, el operador leeria un error de pool en vez de "el rol
    puede saltar RLS", que es lo unico accionable.
    """
    try:
        run_in_worker_loop(engine.dispose())
    except BaseException:
        logger.warning(
            "No se pudo desechar el pool tras verificar el rol", exc_info=True
        )


def _abort_if_settings_are_fallback() -> None:
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

# Beat persiste "ultima corrida" en un archivo. Vive en el volumen
# `beat_schedule` (docker-compose.yml): en /tmp cada recreacion del contenedor
# lo perdia. El directorio lo crea el Dockerfile con dueno appuser, y el
# healthcheck de beat mira este mismo archivo.
BEAT_SCHEDULE_FILE = "/var/lib/shifty/beat/shifty-celerybeat-schedule"

# Vencimiento de cada tick del beat, siempre menor que su periodo (F0-17): si
# el worker se atrasa, los ticks viejos vencen en la cola en vez de correr uno
# detras de otro al recuperarse, y nunca conviven dos del mismo job.
_EXPIRES_20_SEGUNDOS = {"expires": 18}
_EXPIRES_1_MINUTO = {"expires": 55}
_EXPIRES_2_MINUTOS = {"expires": 110}
_EXPIRES_15_MINUTOS = {"expires": 890}
_EXPIRES_DIARIO = {"expires": 3600}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # F0-17: publicar desde un request con el broker caido no puede colgarlo.
    # Antes: 4 s de conexion por intento y tres reintentos.
    broker_connection_timeout=2,
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },
    # Nadie lee el resultado de una tarea. Guardarlo costaba un viaje a Redis
    # por tarea y, con el Redis de resultados caido, cada tarea retenia su slot
    # del worker 20-150 s reintentando.
    task_ignore_result=True,
    # El OTP va a su propia cola, que atiende un worker aparte
    # (celery_worker_interactive, --concurrency=1): su latencia no depende de
    # que termine un lote del outbox (decision 7). Lo demas va a `celery`.
    task_routes={"send_otp_email": {"queue": "interactive"}},
    beat_schedule_filename=BEAT_SCHEDULE_FILE,
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
        # Cada 20 s con lotes de 25 (decision 18): con lotes de 100 el
        # presupuesto de 45 s del lote cortaba mails; lotes chicos y seguidos
        # mantienen el atraso por debajo del minuto. El contrato del outbox
        # (mails despues del commit, processed_at) no cambia.
        "process-payment-outbox-every-20-seconds": {
            "task": "process_payment_outbox",
            "schedule": 20.0,
            "kwargs": {"limit": 25},
            "options": _EXPIRES_20_SEGUNDOS,
        },
        "process-payment-webhook-inbox-every-minute": {
            "task": "process_payment_webhook_inbox",
            "schedule": crontab(),
            "options": _EXPIRES_1_MINUTO,
        },
        "expire-unpaid-appointment-holds-every-minute": {
            "task": "expire_unpaid_appointments",
            "schedule": crontab(),
            "options": _EXPIRES_1_MINUTO,
        },
        # Red de contencion por si un webhook de Mercado Pago nunca llego.
        # Cada 2 minutos: "pague y sigue pendiente" dura menos.
        "reconcile-pending-payments-every-2-minutes": {
            "task": "reconcile_pending_payments",
            "schedule": crontab(minute="*/2"),
            "options": _EXPIRES_2_MINUTOS,
        },
        "process-appointment-reminders-every-15-minutes": {
            "task": "process_appointment_reminders",
            "schedule": crontab(minute="*/15"),
            "options": _EXPIRES_15_MINUTOS,
        },
        # Ofertas de lista de espera vencidas: pasan a la siguiente persona.
        # Cada minuto: una oferta de 10 minutos no puede quedar 5 mas colgada.
        "process-waitlist-offers-every-minute": {
            "task": "process_waitlist_offers",
            "schedule": crontab(),
            "options": _EXPIRES_1_MINUTO,
        },
        # Higiene de la tabla de sesiones: las expiradas/revocadas viejas se
        # purgan a diario (es material de credenciales, no un historico).
        "purge-expired-auth-sessions-daily": {
            "task": "purge_expired_auth_sessions",
            "schedule": crontab(minute=0, hour=4),
            "options": _EXPIRES_DIARIO,
        },
        # Ciclo de vida de la suscripcion: aviso, vencimiento y suspension.
        # 09:00 UTC son las 06:00 en Argentina: el aviso llega temprano.
        "process-subscription-lifecycle-daily": {
            "task": "process_subscription_lifecycle",
            "schedule": crontab(minute=0, hour=9),
            "options": _EXPIRES_DIARIO,
        },
    },
)
