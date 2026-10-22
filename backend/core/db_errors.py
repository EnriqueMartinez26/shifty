"""Clasificacion de errores de base: carrera entre transacciones o fallo real.

Vive aca y no en ``main.py`` porque la usan el handler HTTP de ``DBAPIError``
(``main.py::dbapi_error_handler``, que responde 409
``CONCURRENT_MODIFICATION``) y los servicios que procesan varios items en un
request y tienen que saltear el que perdio la carrera sin abortar el resto
(``AppointmentService.bulk_cancel``).
"""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import StaleDataError

# SQLSTATE de Postgres que son carreras legitimas entre transacciones, no
# fallos del servidor: deadlock_detected, serialization_failure y
# lock_not_available.
#
# 55P03 entra porque la migracion `app_role_timeouts` le pone al rol de la app
# `lock_timeout = '5s'`: en una rafaga sobre el mismo profesional, el que
# espera mas de ese plazo por el `SELECT ... FOR UPDATE` recibe 55P03. Es la
# misma carrera entre dos actores que 40P01, provocada por una guarda propia
# del repo, y salia como 500 (AUD2-B7-02, 2026-09-20). La regla de CLAUDE.md
# §4 exige cero 5xx en la prueba de rafaga.
#
# 57014 (statement_timeout) NO entra: ahi no hay otro actor esperando, es una
# consulta que tardo demasiado, o sea un problema del servidor que tiene que
# seguir siendo 500 visible.
CONCURRENCY_SQLSTATES = frozenset({"40P01", "40001", "55P03"})


def sqlstate_of(exc: DBAPIError) -> str | None:
    """SQLSTATE del error del driver (asyncpg: ``sqlstate``; psycopg: ``pgcode``)."""
    candidatos = [exc.orig, getattr(exc.orig, "__cause__", None)]
    for error in candidatos:
        for atributo in ("sqlstate", "pgcode"):
            valor = getattr(error, atributo, None)
            if isinstance(valor, str):
                return valor
    return None


def is_concurrency_conflict(exc: BaseException) -> bool:
    """La excepcion es una carrera con otra transaccion, no un fallo del servidor.

    Cubre el optimistic locking (``StaleDataError``, columna ``version``) y los
    SQLSTATE de ``CONCURRENCY_SQLSTATES``. Cualquier otro error de base
    (conexion perdida, RLS, timeout de sentencia) NO lo es y tiene que seguir
    subiendo como 500 visible.
    """
    if isinstance(exc, StaleDataError):
        return True
    return isinstance(exc, DBAPIError) and sqlstate_of(exc) in CONCURRENCY_SQLSTATES
