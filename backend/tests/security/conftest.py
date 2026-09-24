"""Fixtures de la suite de seguridad.

Reusa las de ``tests/integration/conftest.py`` (base SQLite en memoria por
test y cliente HTTP contra la app real) para las pruebas de abuso, que
necesitan una base limpia por test, y agrega ``mundo``: dos tiendas armadas
UNA vez por modulo para las pasadas grandes (matriz de roles, IDOR), que con
una base por test tardarian minutos.
"""

import smtplib
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

from core.redis import get_availability_cache, get_redis
from main import app
from tests.integration.conftest import client, test_engine, test_session
from tests.security.mundo import Mundo, RedisFalso, app_con_base_propia

__all__ = ["client", "test_engine", "test_session", "mundo"]


class _SmtpCaido:
    """SMTP que rechaza la conexion en el acto.

    En Windows un connect a un puerto cerrado tarda ~4 s en fallar, y cada
    reserva con email manda un mail best-effort: el armado del mundo pasaba de
    1 s a 30 s. La app sigue por su camino de fallo (loguea y sigue), que es
    justamente el comportamiento que se quiere ejercitar.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionRefusedError("SMTP deshabilitado en la suite de seguridad")


@pytest.fixture(scope="module", autouse=True)
def smtp_caido() -> Iterator[None]:
    parche = pytest.MonkeyPatch()
    parche.setattr(smtplib, "SMTP", _SmtpCaido)
    yield
    parche.undo()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def mundo() -> AsyncIterator[Mundo]:
    # El doble de Redis de tests/conftest.py es de alcance de funcion y todavia
    # no esta puesto cuando se arma el mundo: sin este, el armado le hablaria
    # al Redis real de la maquina.
    redis = RedisFalso()

    async def falso() -> RedisFalso:
        return redis

    dependencias = (get_redis, get_availability_cache)
    for dependencia in dependencias:
        app.dependency_overrides[dependencia] = falso
    try:
        async with app_con_base_propia() as (http, sesiones):
            m = Mundo(http, sesiones)
            await m.armar()
            yield m
    finally:
        for dependencia in dependencias:
            if app.dependency_overrides.get(dependencia) is falso:
                app.dependency_overrides.pop(dependencia)
