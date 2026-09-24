"""Encolar en Celery desde un request tiene tope de tiempo y nunca propaga.

F1-03 (plan de rendimiento, R8-02/R9-04, 2026-09-24): ``send_otp_email.delay``
publicaba en RabbitMQ de forma SINCRONICA dentro del event loop, sin timeout
de conexion ni politica de reintento acotada. Con el broker inalcanzable cada
publish tardaba ~16 s y hasta 33 s con toda la API congelada (el loop no
atendia a nadie mas), y rompia el tiempo neutro del OTP (regla 20).

``core.enqueue.enqueue`` corre el publish en un hilo con ``asyncio.to_thread``
y lo corta a los 2 s con ``asyncio.wait_for``. Un fallo o un timeout se
registran (``enqueue_failed``, nombre de la tarea y tipo de error, sin
argumentos: llevan emails y codigos) y devuelven False.
"""

from __future__ import annotations

import threading
import time

import pytest
from structlog.testing import capture_logs

from core.enqueue import enqueue


class _TareaQueSeCuelga:
    name = "tarea_colgada"

    def __init__(self) -> None:
        self.soltar = threading.Event()

    def delay(self, *_args: object, **_kwargs: object) -> None:
        # Broker que no responde: bloquea el hilo hasta 5 s.
        self.soltar.wait(5)


class _TareaQueFalla:
    name = "tarea_rota"

    def delay(self, *_args: object, **_kwargs: object) -> None:
        raise ConnectionRefusedError("amqp://guest:secreto@broker:5672 inalcanzable")


class _TareaSana:
    name = "tarea_sana"

    def __init__(self) -> None:
        self.recibido: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def delay(self, *args: object, **kwargs: object) -> None:
        self.recibido.append((args, kwargs))


@pytest.mark.asyncio
async def test_un_broker_colgado_no_retiene_al_llamador_mas_que_el_tope() -> None:
    tarea = _TareaQueSeCuelga()
    try:
        inicio = time.monotonic()
        with capture_logs() as eventos:
            encolado = await enqueue(tarea, "a@example.com", timeout=0.2)
        demora = time.monotonic() - inicio
    finally:
        tarea.soltar.set()

    assert encolado is False
    assert demora < 1.0, f"el llamador espero {demora:.2f} s con tope de 0.2 s"
    fallo = next(e for e in eventos if e["event"] == "enqueue_failed")
    assert fallo["task"] == "tarea_colgada"
    assert fallo["error_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_un_error_del_broker_no_propaga_ni_filtra_la_url() -> None:
    with capture_logs() as eventos:
        encolado = await enqueue(_TareaQueFalla(), "a@example.com", "codigo 123456")

    assert encolado is False
    fallo = next(e for e in eventos if e["event"] == "enqueue_failed")
    assert fallo["task"] == "tarea_rota"
    assert fallo["error_type"] == "ConnectionRefusedError"
    assert "secreto" not in str(fallo)
    assert "a@example.com" not in str(fallo)
    assert "123456" not in str(fallo)


@pytest.mark.asyncio
async def test_el_camino_sano_encola_con_los_argumentos() -> None:
    tarea = _TareaSana()

    assert await enqueue(tarea, "a@example.com", "Asunto", prioridad=1) is True
    assert tarea.recibido == [(("a@example.com", "Asunto"), {"prioridad": 1})]


def test_el_tope_por_defecto_es_de_dos_segundos() -> None:
    import inspect

    assert inspect.signature(enqueue).parameters["timeout"].default == 2.0
