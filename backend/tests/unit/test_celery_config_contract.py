"""Contrato de la configuracion de Celery (plan de rendimiento F0-17).

Cada clave responde a un modo de fallo medido (R9 de la auditoria de
rendimiento):

- `task_ignore_result`: nadie lee el resultado de una tarea, pero con el Redis
  de resultados caido cada tarea retenia su slot del worker 20-150 s
  reintentando guardarlo.
- `broker_connection_timeout` y `task_publish_retry_policy`: un `.delay()`
  desde un request con el broker caido esperaba ~4 s por intento con varios
  reintentos, con el request colgado. Ahora: 2 s y un reintento corto.
- `expires` en cada entrada del beat: si el worker se atrasa, los ticks viejos
  vencen en la cola en vez de correr uno detras de otro al recuperarse (un
  minuto de atraso eran N corridas del mismo lote). Siempre menor que el
  periodo: nunca conviven dos ticks del mismo job en la cola.
- El outbox corre cada 20 s con un lote de 25: el presupuesto de 45 s del lote
  cortaba mails cuando el lote era de 100 (decision 18).
- El OTP va a la cola `interactive`, que atiende un worker propio: su latencia
  no depende de que termine un lote del outbox (decision 7).
"""

from datetime import timedelta
from pathlib import Path

import pytest
from celery.schedules import crontab

from core.celery_app import celery_app

# Tarea -> (periodo en segundos, expires esperado).
CADENCIA = {
    "process_payment_outbox": (20, 18),
    "process_payment_webhook_inbox": (60, 55),
    "expire_unpaid_appointments": (60, 55),
    "process_waitlist_offers": (60, 55),
    "reconcile_pending_payments": (120, 110),
    "process_appointment_reminders": (900, 890),
    "purge_expired_auth_sessions": (86400, 3600),
    "process_subscription_lifecycle": (86400, 3600),
}


def _entradas() -> dict[str, dict[str, object]]:
    return {
        str(entrada["task"]): entrada
        for entrada in celery_app.conf.beat_schedule.values()
    }


def _periodo(schedule: object) -> float:
    if isinstance(schedule, (int, float)):
        return float(schedule)
    if isinstance(schedule, timedelta):
        return schedule.total_seconds()
    assert isinstance(schedule, crontab), schedule
    minutos = sorted(schedule.minute)
    horas = sorted(schedule.hour)
    if len(horas) == 24 and len(minutos) > 1:
        return float((minutos[1] - minutos[0]) * 60)
    if len(horas) == 24:
        return 3600.0
    return 86400.0


def test_nadie_espera_resultados_de_las_tareas() -> None:
    assert celery_app.conf.task_ignore_result is True


def test_publicar_con_el_broker_caido_no_cuelga_el_request() -> None:
    assert celery_app.conf.broker_connection_timeout == 2
    assert celery_app.conf.task_publish_retry_policy == {
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    }


def test_el_otp_va_a_la_cola_interactiva() -> None:
    celery_app.loader.import_default_modules()
    assert "send_otp_email" in celery_app.tasks, "la tarea del OTP cambio de nombre"
    assert celery_app.conf.task_routes == {"send_otp_email": {"queue": "interactive"}}
    # Todo lo demas sigue en la cola por defecto, que consume el worker general.
    assert celery_app.conf.task_default_queue == "celery"


def test_cada_job_del_beat_tiene_su_cadencia_y_vence_antes_del_siguiente() -> None:
    celery_app.loader.import_default_modules()
    entradas = _entradas()
    assert set(entradas) == set(CADENCIA), sorted(entradas)
    for tarea, (periodo, expires) in CADENCIA.items():
        entrada = entradas[tarea]
        assert tarea in celery_app.tasks, f"{tarea} no esta registrada"
        assert _periodo(entrada["schedule"]) == periodo, (tarea, entrada["schedule"])
        opciones = entrada.get("options") or {}
        assert isinstance(opciones, dict)
        assert opciones.get("expires") == expires, (tarea, opciones)
        assert expires < periodo, (tarea, expires, periodo)


def test_el_outbox_procesa_lotes_chicos_y_seguidos() -> None:
    entrada = _entradas()["process_payment_outbox"]
    assert entrada.get("kwargs") == {"limit": 25}, entrada


@pytest.mark.parametrize("tarea", ["reconcile_pending_payments"])
def test_la_conciliacion_corre_cada_dos_minutos(tarea: str) -> None:
    schedule = _entradas()[tarea]["schedule"]
    assert isinstance(schedule, crontab)
    assert sorted(schedule.minute) == list(range(0, 60, 2))


def test_beat_persiste_su_schedule_en_el_volumen() -> None:
    """Antes en /tmp: cada recreacion del contenedor lo perdia y beat
    recalculaba; con el volumen `beat_schedule` sobrevive al deploy."""
    archivo = Path(str(celery_app.conf.beat_schedule_filename))
    assert archivo.as_posix() == "/var/lib/shifty/beat/shifty-celerybeat-schedule"


# --- Latido del worker (F0-18, decision 7) ------------------------------------
#
# El healthcheck del worker era `celery inspect ping`: levantaba un Python
# completo (~120 MB) dentro del cgroup del worker cada minuto, con el peor caso
# por encima del limite. Ahora el worker toca un archivo en cada latido de
# eventos (`heartbeat_sent`, cada 2 s) y el healthcheck mira su antiguedad con
# `find`. El latido lo emite el consumidor sobre su conexion al broker: si la
# conexion se cae o el loop del consumidor se traba, deja de latir y el archivo
# envejece. Sigue detectando "vivo pero sin consumir" (AUD2-C-09).


def test_el_worker_late_en_un_archivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from celery.signals import heartbeat_sent

    import core.celery_app as modulo

    assert modulo.WORKER_HEARTBEAT_FILE == "/var/lib/shifty/worker-heartbeat"
    archivo = tmp_path / "worker-heartbeat"
    monkeypatch.setattr(modulo, "WORKER_HEARTBEAT_FILE", str(archivo))

    heartbeat_sent.send(sender=None)
    assert archivo.exists(), "el latido no creo el archivo"

    os.utime(archivo, (0, 0))
    heartbeat_sent.send(sender=None)
    assert archivo.stat().st_mtime > 0, "el latido no renovo el archivo"


def test_un_latido_que_no_puede_escribir_no_tumba_al_worker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """El handler se llama DIRECTO, no por `Signal.send`: el despachador de
    signals de Celery atrapa las excepciones de los receptores, asi que por ahi
    el test pasaba aunque el handler levantara. Un disco que no acepta la
    escritura se ve como unhealthy en el healthcheck y queda en el log, pero el
    consumidor no puede morir por eso."""
    import logging

    import core.celery_app as modulo

    def touch_que_falla(*_: object, **__: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "touch", touch_que_falla)
    with caplog.at_level(logging.WARNING, logger=modulo.logger.name):
        modulo._touch_worker_heartbeat()

    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert avisos, "el latido fallido no dejo rastro en el log"
    assert "worker_heartbeat_touch_failed" in avisos[0].getMessage()
