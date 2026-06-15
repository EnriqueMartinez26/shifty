"""
Módulo de auditoría.

Registra cada acción relevante de negocio con el contexto completo:
quién la hizo, sobre qué recurso, cuál era el estado antes y después.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, ForeignKey, DateTime, func, JSON, Text

from core.models import Base


# ---------------------------------------------------------------------------
# Enum de acciones auditables
# ---------------------------------------------------------------------------


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"  # Soft delete (is_active = False)
    STATUS_CHANGE = "status_change"


# ---------------------------------------------------------------------------
# Modelo AuditLog
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """
    Tabla de auditoría inmutable.

    No hereda de BaseEntity intencionalmente:
    - No tiene public_id (se usa id interno para performance).
    - No tiene is_active (nunca se borra un log de auditoría).
    - No tiene updated_at (un log es inmutable por definición).
    """

    __tablename__ = "audit_logs"

    # PK simple, sin ULID para máxima performance de inserción
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Cuándo ocurrió la acción (server-side, no confiar en el cliente)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    # Quién realizó la acción (nullable para acciones del sistema / Celery)
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor_public_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Sobre qué entidad
    resource_type: Mapped[str] = mapped_column(
        String(100), index=True
    )  # ej: "Appointment"
    resource_id: Mapped[str] = mapped_column(
        String(26), index=True
    )  # public_id del recurso

    # Qué acción se realizó
    action: Mapped[str] = mapped_column(String(50))  # AuditAction value

    # Estado anterior y posterior (JSON libre para flexibilidad sin migración)
    payload_before: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    payload_after: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    # Contexto adicional (IP, user agent, etc.)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
