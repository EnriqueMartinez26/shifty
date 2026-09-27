"""Versiones vigentes de los textos legales y su control al aceptar.

2026-09-25, PV-09 y L1 (O-3, O-4). ``terms_accepted_at`` sola no prueba que
texto rigio. El portal lee las versiones de ``GET /public/legal/versions`` y
las manda con la aceptacion; aca se comparan con las vigentes (settings).
Una version distinta es 409 ``LEGAL_VERSION_MISMATCH``: el cliente vio un
texto que ya no rige y el front tiene que volver a mostrarle la casilla.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated

from pydantic import Field

from core.config import LEGAL_VERSION_PATTERN, settings
from core.exceptions import AppException, ValidationException

LegalVersion = Annotated[
    str, Field(min_length=1, max_length=20, pattern=LEGAL_VERSION_PATTERN)
]


class LegalVersionMismatchException(AppException):
    def __init__(self) -> None:
        super().__init__(
            message=(
                "Los terminos o la politica de privacidad cambiaron. Volve a "
                "leerlos y aceptarlos."
            ),
            http_status=HTTPStatus.CONFLICT,
            error_code="LEGAL_VERSION_MISMATCH",
            detail=current_versions(),
        )


def current_versions() -> dict[str, str]:
    """Las versiones que rigen hoy (se leen en cada llamada: un cambio de
    settings no necesita reiniciar nada mas que el proceso)."""
    return {
        "terms_version": settings.LEGAL_TERMS_VERSION,
        "privacy_version": settings.LEGAL_PRIVACY_VERSION,
    }


@dataclass(frozen=True)
class AcceptedVersions:
    terms_version: str | None = None
    privacy_version: str | None = None


def check_accepted_versions(
    terms_version: str | None,
    privacy_version: str | None,
    *,
    required: bool = False,
) -> AcceptedVersions:
    """Las versiones que el cliente acepto, si son las vigentes.

    Sin ninguna de las dos y sin ``required``: se acepta (compatibilidad con
    el front que todavia no las manda) y no se inventa una version. Con una
    sola: 422 (pedido mal armado, no "los textos cambiaron"; revision de
    fix/legal-datos, 2026-09-25). Distintas de las vigentes: 409. Con
    ``required`` y sin ellas: 422.

    Los llamadores lo corren despues del replay de idempotencia (la guarda
    del router va antes que el caso de uso): el reintento de una reserva ya
    hecha devuelve la original aunque los textos hayan cambiado despues.
    """
    if terms_version is None and privacy_version is None:
        if required:
            raise ValidationException(
                "Faltan las versiones de los terminos y de la politica de privacidad"
            )
        return AcceptedVersions()
    if terms_version is None or privacy_version is None:
        raise ValidationException(
            "Hay que mandar las dos versiones: terminos y politica de privacidad"
        )
    vigentes = current_versions()
    if (terms_version, privacy_version) != (
        vigentes["terms_version"],
        vigentes["privacy_version"],
    ):
        raise LegalVersionMismatchException()
    return AcceptedVersions(terms_version, privacy_version)


__all__ = [
    "AcceptedVersions",
    "LegalVersion",
    "LegalVersionMismatchException",
    "check_accepted_versions",
    "current_versions",
]
