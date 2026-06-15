"""
Catálogo centralizado de excepciones de dominio.

Principio: cada excepción transporta su propio código HTTP
para que el handler global pueda convertirla sin lógica extra.
Los routers NUNCA deben importar HTTPException de FastAPI directamente
como mecanismo de validación de negocio; lo hacen solo para errores
técnicos de ruta (ej. 404 "recurso no existe").
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from typing import Any


# ---------------------------------------------------------------------------
# BASE
# ---------------------------------------------------------------------------


@dataclass
class AppException(Exception):
    """
    Excepción base del dominio de Shifty.
    Todos los errores de negocio heredan de aquí.
    """

    message: str
    http_status: int = 400
    # Código máquina legible por el frontend (e.g. "APPOINTMENT_CONFLICT")
    error_code: str = "APP_ERROR"
    # Metadata adicional para contexto (ej. el public_id del recurso conflictivo)
    detail: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


# ---------------------------------------------------------------------------
# TURNOS
# ---------------------------------------------------------------------------


class AppointmentConflictException(AppException):
    """El horario solicitado ya está ocupado por otra reserva."""

    def __init__(
        self,
        conflict_start: datetime | None = None,
        conflict_end: datetime | None = None,
        suggestion: datetime | None = None,
    ) -> None:
        message = "El horario solicitado ya no está disponible."
        if conflict_start and conflict_end:
            # Formatear horarios para que el usuario sepa EXACTAMENTE qué está ocupado
            start_str = conflict_start.strftime("%H:%M")
            end_str = conflict_end.strftime("%H:%M")
            message = f"El profesional ya tiene un turno de {start_str} a {end_str}. "
            if suggestion:
                sugg_str = suggestion.strftime("%H:%M")
                message += f"Te sugerimos intentar a las {sugg_str}."
            else:
                message += f"Por favor, intenta reservar a partir de las {end_str}."

        super().__init__(
            message=message,
            http_status=HTTPStatus.CONFLICT,
            error_code="APPOINTMENT_CONFLICT",
            detail={
                "conflict_start": conflict_start.isoformat()
                if conflict_start
                else None,
                "conflict_end": conflict_end.isoformat() if conflict_end else None,
                "suggestion": suggestion.isoformat() if suggestion else None,
            },
        )


class AppointmentNotFoundException(AppException):
    """El turno referenciado no existe en el tenant actual."""

    def __init__(self, public_id: str) -> None:
        super().__init__(
            message=f"Turno '{public_id}' no encontrado.",
            http_status=HTTPStatus.NOT_FOUND,
            error_code="APPOINTMENT_NOT_FOUND",
            detail={"public_id": public_id},
        )


class InvalidStatusTransitionException(AppException):
    """
    Intento de transición inválida de estado.
    Ej: intentar confirmar un turno que ya fue cancelado.
    """

    def __init__(self, current: str, attempted: str) -> None:
        super().__init__(
            message=f"No se puede pasar de '{current}' a '{attempted}'.",
            http_status=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="INVALID_STATUS_TRANSITION",
            detail={"current_status": current, "attempted_status": attempted},
        )


# ---------------------------------------------------------------------------
# RECURSOS GENERALES
# ---------------------------------------------------------------------------


class ResourceNotFoundException(AppException):
    """Recurso genérico no encontrado (Staff, Servicio, etc.)."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            message=f"{resource} '{identifier}' no encontrado.",
            http_status=HTTPStatus.NOT_FOUND,
            error_code="RESOURCE_NOT_FOUND",
            detail={"resource": resource, "identifier": identifier},
        )


class BlockedScheduleException(AppException):
    """El horario solicitado está bloqueado por el profesional o el salón."""

    def __init__(
        self,
        reason: str | None = None,
        block_start: datetime | None = None,
        block_end: datetime | None = None,
        suggestion: datetime | None = None,
    ) -> None:
        message = "El profesional no está disponible en ese horario."
        if block_start and block_end:
            start_str = block_start.strftime("%H:%M")
            end_str = block_end.strftime("%H:%M")
            message = f"La agenda está bloqueada de {start_str} a {end_str}"
            if reason:
                message += f" (Razón: {reason})."
            else:
                message += "."

            if suggestion:
                sugg_str = suggestion.strftime("%H:%M")
                message += f" Podés reservar a partir de las {sugg_str}."
        elif reason:
            message = f"Horario no disponible: {reason}."

        super().__init__(
            message=message,
            http_status=HTTPStatus.CONFLICT,
            error_code="SCHEDULE_BLOCKED",
            detail={
                "reason": reason or "Bloqueo de agenda",
                "block_start": block_start.isoformat() if block_start else None,
                "block_end": block_end.isoformat() if block_end else None,
                "suggestion": suggestion.isoformat() if suggestion else None,
            },
        )


class BookingNoticeException(AppException):
    """Lanzada cuando se intenta agendar fuera de la ventana permitida (Don Norman: Constraint)."""

    def __init__(self, hours: int) -> None:
        super().__init__(
            message=f"Este local requiere {hours}h de anticipación para agendar/reprogramar.",
            http_status=HTTPStatus.BAD_REQUEST,
            error_code="BOOKING_NOTICE_REQUIRED",
            detail={"notice_hours_required": hours},
        )


class IdempotencyInProgressException(AppException):
    """La misma operación está siendo procesada por otra petición."""

    def __init__(self) -> None:
        super().__init__(
            message="La operación ya está en proceso. Reintentá en unos segundos.",
            http_status=HTTPStatus.CONFLICT,
            error_code="IDEMPOTENCY_IN_PROGRESS",
        )


class PermissionDeniedException(AppException):
    """El usuario no tiene permisos para realizar esta operación."""

    def __init__(self, action: str = "") -> None:
        super().__init__(
            message=f"No tenés permiso para realizar esta acción{': ' + action if action else ''}.",
            http_status=HTTPStatus.FORBIDDEN,
            error_code="PERMISSION_DENIED",
        )


# ---------------------------------------------------------------------------
# AUTENTICACIÓN
# ---------------------------------------------------------------------------


class AuthenticationException(AppException):
    """Credenciales inválidas o sesión expirada."""

    def __init__(self, message: str = "Credenciales inválidas.") -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.UNAUTHORIZED,
            error_code="AUTHENTICATION_FAILED",
        )


class InvalidTokenException(AppException):
    """Token JWT inválido, expirado o corrupto."""

    def __init__(self, message: str = "Token inválido o expirado.") -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.BAD_REQUEST,
            error_code="INVALID_TOKEN",
        )


class RegistrationDisabledException(AppException):
    """El registro público está deshabilitado para este tenant."""

    def __init__(self) -> None:
        super().__init__(
            message="El registro público no está habilitado.",
            http_status=HTTPStatus.FORBIDDEN,
            error_code="REGISTRATION_DISABLED",
        )


class DuplicateAccountException(AppException):
    """Ya existe una cuenta con ese email o teléfono."""

    def __init__(self, field: str = "email") -> None:
        super().__init__(
            message=f"Ya existe una cuenta con ese {field}.",
            http_status=HTTPStatus.CONFLICT,
            error_code="DUPLICATE_ACCOUNT",
            detail={"field": field},
        )


# ---------------------------------------------------------------------------
# VALIDACIÓN
# ---------------------------------------------------------------------------


class ValidationException(AppException):
    """Error de validación de negocio (no de schema Pydantic)."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            detail=detail or {},
        )


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------


class OTPException(AppException):
    """Error en el flujo de verificación OTP."""

    def __init__(
        self,
        message: str = "Código OTP inválido o expirado.",
        error_code: str = "OTP_INVALID",
        http_status: int = HTTPStatus.BAD_REQUEST,
    ) -> None:
        super().__init__(
            message=message,
            http_status=http_status,
            error_code=error_code,
        )


class OTPRateLimitedException(AppException):
    """Demasiados intentos de OTP."""

    def __init__(self, retry_after_seconds: int = 60) -> None:
        super().__init__(
            message="Demasiados intentos. Esperá antes de solicitar otro código.",
            http_status=HTTPStatus.TOO_MANY_REQUESTS,
            error_code="OTP_RATE_LIMITED",
            detail={"retry_after_seconds": retry_after_seconds},
        )


# ---------------------------------------------------------------------------
# PAGOS
# ---------------------------------------------------------------------------


class PaymentException(AppException):
    """Error genérico en operaciones de pago."""

    def __init__(
        self,
        message: str = "Error en la operación de pago.",
        error_code: str = "PAYMENT_ERROR",
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.BAD_REQUEST,
            error_code=error_code,
            detail=detail or {},
        )


class WebhookException(AppException):
    """Error procesando un webhook externo."""

    def __init__(
        self,
        message: str = "Error procesando webhook.",
        http_status: int = HTTPStatus.BAD_REQUEST,
        error_code: str = "WEBHOOK_ERROR",
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            http_status=http_status,
            error_code=error_code,
            detail=detail or {},
        )


# ---------------------------------------------------------------------------
# RECURSOS ESPECÍFICOS (NOT FOUND)
# ---------------------------------------------------------------------------


class StoreNotFoundException(AppException):
    """La tienda referenciada no existe."""

    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            message=f"Tienda{' ' + repr(identifier) if identifier else ''} no encontrada.",
            http_status=HTTPStatus.NOT_FOUND,
            error_code="STORE_NOT_FOUND",
            detail={"identifier": identifier} if identifier else {},
        )


class UserNotFoundException(AppException):
    """El usuario referenciado no existe."""

    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            message=f"Usuario{' ' + repr(identifier) if identifier else ''} no encontrado.",
            http_status=HTTPStatus.NOT_FOUND,
            error_code="USER_NOT_FOUND",
            detail={"identifier": identifier} if identifier else {},
        )


class ServiceNotFoundException(AppException):
    """El servicio referenciado no existe."""

    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            message=f"Servicio{' ' + repr(identifier) if identifier else ''} no encontrado.",
            http_status=HTTPStatus.NOT_FOUND,
            error_code="SERVICE_NOT_FOUND",
            detail={"identifier": identifier} if identifier else {},
        )


class StaffNotFoundException(AppException):
    """El profesional referenciado no existe."""

    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            message=f"Profesional{' ' + repr(identifier) if identifier else ''} no encontrado.",
            http_status=HTTPStatus.NOT_FOUND,
            error_code="STAFF_NOT_FOUND",
            detail={"identifier": identifier} if identifier else {},
        )


# ---------------------------------------------------------------------------
# OPERACIONES
# ---------------------------------------------------------------------------


class FeatureDisabledException(AppException):
    """La funcionalidad solicitada está deshabilitada por feature flag."""

    def __init__(self, feature: str = "") -> None:
        super().__init__(
            message=f"Funcionalidad no disponible{': ' + feature if feature else ''}.",
            http_status=HTTPStatus.FORBIDDEN,
            error_code="FEATURE_DISABLED",
            detail={"feature": feature} if feature else {},
        )


class RateLimitedException(AppException):
    """Demasiadas solicitudes."""

    def __init__(
        self,
        message: str = "Demasiadas solicitudes. Intentá nuevamente más tarde.",
        retry_after: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            http_status=HTTPStatus.TOO_MANY_REQUESTS,
            error_code="RATE_LIMITED",
            detail={"retry_after": retry_after} if retry_after else {},
            headers=headers or {},
        )
