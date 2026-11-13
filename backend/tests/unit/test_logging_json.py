"""F0-22 (plan de rendimiento): los logs de la app salen en JSON, una linea cada uno.

Sin configuracion, structlog escribe con ConsoleRenderer: texto con colores
pensado para una terminal. En `docker compose logs` eso no se puede filtrar
por campo, y un traceback ocupa varias lineas que el driver json-file guarda
como eventos separados. Ahora cada evento es un objeto JSON con timestamp ISO
en UTC, nivel y el contexto que se haya ligado con
`structlog.contextvars.bind_contextvars` (por ejemplo, el id del request).
"""

import io
import json
from collections.abc import Iterator

import pytest
import structlog

from core.config import settings
from core.logging import configure_logging


@pytest.fixture
def salida() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    yield buffer
    structlog.contextvars.clear_contextvars()
    # Deja la configuracion como la deja la app (main.py la aplica al importar).
    configure_logging()


def _eventos(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(linea) for linea in buffer.getvalue().splitlines() if linea]


def test_cada_evento_es_una_linea_json(salida: io.StringIO) -> None:
    configure_logging(stream=salida)
    structlog.contextvars.bind_contextvars(request_id="req-123")

    structlog.get_logger().info("reserva_creada", store_id="st-1")

    (evento,) = _eventos(salida)
    assert evento["event"] == "reserva_creada"
    assert evento["level"] == "info"
    assert evento["store_id"] == "st-1"
    # merge_contextvars: el contexto del request viaja sin pasarlo a mano.
    assert evento["request_id"] == "req-123"
    timestamp = str(evento["timestamp"])
    assert timestamp.endswith("Z") and "T" in timestamp, timestamp


def test_una_excepcion_queda_en_el_mismo_evento(salida: io.StringIO) -> None:
    configure_logging(stream=salida)
    try:
        raise RuntimeError("fallo de prueba")
    except RuntimeError:
        structlog.get_logger().error("job_fallo", exc_info=True)

    (evento,) = _eventos(salida)
    assert "RuntimeError: fallo de prueba" in str(evento["exception"])


def test_el_nivel_sale_de_la_configuracion(
    salida: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    nivel_original = settings.LOG_LEVEL
    # El fixture ``salida`` vuelve a configurar structlog al terminar. Restaura
    # el nivel antes de ese teardown para que no quede filtrando INFO en otras
    # pruebas que comparten el logger global.
    try:
        with monkeypatch.context() as nivel_base:
            nivel_base.setattr(settings, "LOG_LEVEL", "INFO")
            with monkeypatch.context() as nivel_temporal:
                nivel_temporal.setattr(settings, "LOG_LEVEL", "WARNING")
                configure_logging(stream=salida)

                structlog.get_logger().info("ruido")
                structlog.get_logger().warning("importa")

        assert [e["event"] for e in _eventos(salida)] == ["importa"]
        assert settings.LOG_LEVEL == "INFO"

        # Reproduce la secuencia que sigue al test: configure_logging() con el
        # nivel base restaurado debe volver a aceptar INFO.
        configure_logging(stream=salida)
        structlog.get_logger().info("nivel_restaurado")
        assert [e["event"] for e in _eventos(salida)] == [
            "importa",
            "nivel_restaurado",
        ]
    finally:
        settings.LOG_LEVEL = nivel_original
        configure_logging()

    assert settings.LOG_LEVEL == nivel_original


def test_el_nivel_por_defecto_es_info() -> None:
    assert type(settings).model_fields["LOG_LEVEL"].default == "INFO"
