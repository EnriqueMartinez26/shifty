"""
Servicio de auditoría.

Responsabilidad única: insertar registros en audit_logs.
Se inyecta en los servicios de negocio que necesiten rastrear cambios.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditAction, AuditLog
from modules.users.model import User


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(
        self,
        *,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        actor: User | None = None,
        payload_before: dict[str, Any] | None = None,
        payload_after: dict[str, Any] | None = None,
        context: str | None = None,
    ) -> None:
        """
        Inserta un registro de auditoría.

        No hace commit por sí mismo: el commit lo realiza el servicio
        de negocio que encapsula toda la operación atómica.
        """
        entry = AuditLog(
            actor_id=actor.id if actor else None,
            actor_public_id=actor.public_id if actor else None,
            actor_email=actor.email if actor else None,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action.value,
            payload_before=payload_before,
            payload_after=payload_after,
            context=context,
        )
        self.db.add(entry)
        # No hacer flush aquí: se escribe en el mismo commit del servicio
