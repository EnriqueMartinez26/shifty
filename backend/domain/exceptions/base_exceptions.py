"""
Excepciones del dominio puro.

Estas excepciones heredan de AppException para que el handler global
las convierta automáticamente en respuestas canónicas sin lógica extra.
El dominio NO importa nada de FastAPI; AppException es un dataclass
plano que solo transporta message, http_status, error_code y detail.
"""

from http import HTTPStatus
from typing import Any

from core.exceptions import AppException


class DomainException(AppException):
    """Base class for all domain exceptions."""

    def __init__(
        self,
        message: str,
        http_status: int = HTTPStatus.BAD_REQUEST,
        error_code: str = "DOMAIN_ERROR",
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            http_status=http_status,
            error_code=error_code,
            detail=detail or {},
        )


class EntityNotFoundError(DomainException):
    """Raised when an entity is not found in the domain."""

    def __init__(self, message: str = "Entidad no encontrada.") -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.NOT_FOUND,
            error_code="ENTITY_NOT_FOUND",
        )


class BusinessRuleViolationError(DomainException):
    """Raised when a business rule is violated."""

    def __init__(
        self,
        message: str = "Regla de negocio violada.",
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="BUSINESS_RULE_VIOLATION",
            detail=detail,
        )


class ConflictError(DomainException):
    """Raised when there is a conflict in the domain (e.g. duplicate resource)."""

    def __init__(
        self,
        message: str = "Conflicto con el estado actual del recurso.",
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.CONFLICT,
            error_code="CONFLICT",
            detail=detail,
        )


class UnauthorizedError(DomainException):
    """Raised when an action is unauthorized at the domain level."""

    def __init__(self, message: str = "Acción no autorizada.") -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.FORBIDDEN,
            error_code="UNAUTHORIZED",
        )
