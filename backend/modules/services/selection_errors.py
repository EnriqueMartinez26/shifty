"""Los rechazos HTTP de una seleccion de varios servicios (decision de Mateo,
2026-10-16). Una sola fuente para la reserva publica, los previews y las dos
disponibilidades: el mismo pedido rebota con el mismo codigo en todos lados.

Las reglas puras viven en ``modules/services/selection.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.exceptions import AppException
from core.feature_flags import is_store_feature_enabled
from modules.services.selection import (
    MAX_SERVICES_PER_APPOINTMENT,
    MAX_TOTAL_DURATION_MINUTES,
    too_many_services,
)

MULTI_SERVICE_FLAG = "multi_service_booking"


def multi_service_disabled() -> AppException:
    return AppException(
        message="Este negocio no toma varios servicios en un mismo turno",
        http_status=422,
        error_code="MULTI_SERVICE_DISABLED",
    )


def too_many_services_error() -> AppException:
    return AppException(
        message=(
            f"Podés elegir hasta {MAX_SERVICES_PER_APPOINTMENT} servicios "
            "en un mismo turno"
        ),
        http_status=422,
        error_code="TOO_MANY_SERVICES",
    )


def services_too_long() -> AppException:
    return AppException(
        message=(
            "Los servicios elegidos duran más de "
            f"{MAX_TOTAL_DURATION_MINUTES // 60} horas: reservalos en turnos separados"
        ),
        http_status=422,
        error_code="SERVICES_TOO_LONG",
    )


def require_selection_size(extra_service_ids: Sequence[str]) -> None:
    """Solo el tope de cantidad (422 ``TOO_MANY_SERVICES``), SIN el flag.

    Para las dos disponibilidades, que son de lectura: apagar el flag no
    puede dejar sin grilla la reprogramacion de un turno de varios servicios
    ya tomado (revision adversarial de #195). El flag lo exigen el alta y los
    dos previews (``require_selection_allowed``).
    """
    if too_many_services(extra_service_ids):
        raise too_many_services_error()


def require_selection_allowed(
    feature_flags: dict[str, Any] | None, extra_service_ids: Sequence[str]
) -> None:
    """Sin extras no hace nada (la reserva de siempre). Con extras: el flag de
    la tienda prendido (si no, 422 ``MULTI_SERVICE_DISABLED``) y no mas de
    ``MAX_SERVICES_PER_APPOINTMENT`` en total (422 ``TOO_MANY_SERVICES``).
    Antes de leer ningun servicio."""
    if not extra_service_ids:
        return
    if not is_store_feature_enabled(feature_flags, MULTI_SERVICE_FLAG):
        raise multi_service_disabled()
    if too_many_services(extra_service_ids):
        raise too_many_services_error()
