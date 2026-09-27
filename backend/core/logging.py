"""Logs de la app en JSON, una linea por evento (plan de rendimiento F0-22).

Sin configuracion, structlog usa ConsoleRenderer: texto con colores para una
terminal, que en `docker compose logs` no se filtra por campo y cuyo traceback
ocupa varias lineas (eventos separados para el driver json-file). Aca cada
evento sale como un objeto JSON con:

- `timestamp` ISO 8601 en UTC y `level`;
- el contexto ligado con `structlog.contextvars.bind_contextvars` (por ejemplo
  el id del request que manda el borde), sin pasarlo a mano en cada llamada;
- la excepcion formateada dentro del MISMO evento.

Lo llaman una vez `main.py` (API) y el arranque de Celery (worker y beat). No
registra cuerpos de request: loguear un body es una decision de cada llamador
y la regla es no hacerlo (pueden traer passwords, tokens y datos personales).

El modulo se llama `core.logging`; dentro del paquete `core` los `import
logging` absolutos siguen resolviendo a la biblioteca estandar.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

import structlog

from core.config import settings


def configure_logging(*, stream: TextIO | None = None) -> None:
    """Configura structlog para emitir JSON al nivel de ``settings.LOG_LEVEL``.

    Idempotente: se puede llamar mas de una vez (tests, recarga). ``stream``
    existe para los tests; en la app los logs van a stdout, que es lo que
    recoge el driver de logs de docker. Sin ``cache_logger_on_first_use``: los
    loggers de modulo se crean al importar, antes de esta llamada, y
    ``structlog.testing.capture_logs`` necesita poder reconfigurarlos.
    """
    nivel = logging.getLevelNamesMapping()[settings.LOG_LEVEL]
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(nivel),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )
