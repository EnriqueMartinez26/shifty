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
    # Derechos del titular (PV-05, 2026-09-25): exportar y anonimizar a un
    # cliente. La fila no lleva datos personales, solo el hecho.
    EXPORT = "export"
    ANONYMIZE = "anonymize"


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

    # PK simple, sin ULID para máxima performance de inserción. Es un contador
    # GLOBAL: nunca sale tal cual hacia afuera, ni siquiera al superadmin; las
    # respuestas usan ``modules.audit.public_id.opaque_audit_log_id``
    # (AUD2-B3-14).
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Cuándo ocurrió la acción (server-side, no confiar en el cliente).
    # timestamptz como el resto del esquema (regla 24, B5-13): naive, now()
    # quedaba en la hora de pared de la sesion y el front no podia convertirlo.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
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

    # Tienda a la que pertenece la accion (B3-11, 2026-09-18). NULL para lo
    # global (planes, cupones) y para filas cuyo recurso no permitio derivarla.
    # Sin FK a proposito: un log es inmutable y sobrevive a su recurso. La
    # tabla sigue fuera de RLS (c3d4e5f6a7b8_rls_efectivo).
    store_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Qué acción se realizó
    action: Mapped[str] = mapped_column(String(50))  # AuditAction value

    # Estado anterior y posterior (JSON libre para flexibilidad sin migración)
    payload_before: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    payload_after: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    # Contexto adicional (IP, user agent, etc.)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
