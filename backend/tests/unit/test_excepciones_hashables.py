"""Las excepciones de dominio se comparan por identidad y son hashables.

2026-09-18 (audit B7-10). Sintoma: `@dataclass` sobre `AppException` genera
`__eq__` por valor y, como consecuencia, pone `__hash__ = None`. Lo heredan
las ~20 subclases: `hash(exc)` levantaba `TypeError: unhashable type`, meterla
en un `set` o usarla de clave de dict (deduplicacion de errores, colectores
de reintentos, `logging` con filtros por excepcion) reventaba, y dos
`AppointmentNotFoundException('p1')` DISTINTAS comparaban iguales.

`@dataclass(eq=False)` vuelve a la semantica de `Exception` (identidad) sin
tocar los campos. La regla 20 depende de esos campos: el handler global de
`main.py` los lee para armar la respuesta neutra, y eso tiene que quedar
exactamente igual.
"""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from core.exceptions import (
    AppException,
    AppointmentNotFoundException,
    RateLimitedException,
    ValidationException,
)


def test_una_excepcion_de_dominio_es_hashable() -> None:
    exc = AppointmentNotFoundException("p1")

    assert isinstance(hash(exc), int)
    assert {exc: "ok"}[exc] == "ok"
    assert exc in {exc}


def test_dos_instancias_con_los_mismos_datos_no_son_la_misma() -> None:
    primera = AppointmentNotFoundException("p1")
    segunda = AppointmentNotFoundException("p1")

    assert primera != segunda
    assert primera == primera
    assert len({primera, segunda}) == 2


def test_la_base_tambien_es_hashable() -> None:
    assert hash(AppException(message="x")) != hash(AppException(message="x"))


def test_los_campos_siguen_siendo_los_del_dataclass() -> None:
    """Riesgo del cambio: perder el `__init__` o el `repr` generados."""
    exc = AppException(message="m", http_status=409, error_code="C", detail={"a": 1})

    assert (exc.message, exc.http_status, exc.error_code, exc.detail) == (
        "m",
        409,
        "C",
        {"a": 1},
    )
    assert exc.headers == {}
    assert str(exc) == "m"
    assert repr(exc).startswith("AppException(message='m'")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status", "codigo"),
    [
        (
            AppointmentNotFoundException("p1"),
            HTTPStatus.NOT_FOUND,
            "APPOINTMENT_NOT_FOUND",
        ),
        (ValidationException("dato invalido", {"campo": "x"}), 422, "VALIDATION_ERROR"),
        (
            RateLimitedException(retry_after=7, headers={"Retry-After": "7"}),
            429,
            "RATE_LIMITED",
        ),
    ],
)
async def test_el_handler_global_sigue_armando_la_misma_respuesta(
    exc: AppException, status: int, codigo: str
) -> None:
    """Regla 20: la respuesta neutra sale de los campos, no de la igualdad."""
    import main

    respuesta = await main.app_exception_handler(None, exc)  # type: ignore[arg-type]

    assert respuesta.status_code == status
    cuerpo = json.loads(bytes(respuesta.body))
    assert codigo in json.dumps(cuerpo)
    assert exc.message in json.dumps(cuerpo, ensure_ascii=False)
    for clave, valor in exc.headers.items():
        assert respuesta.headers[clave] == valor
