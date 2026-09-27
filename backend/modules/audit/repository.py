"""
Repositorio de auditoría.

Persiste filas en ``audit_logs`` y lee la auditoria de turnos de una tienda
(B5-12). No toma decisiones de negocio y no commitea. Antes se llamaba
``AuditService``, un nombre que sugeria logica que nunca tuvo.

``audit_logs`` esta FUERA de RLS (c3d4e5f6a7b8_rls_efectivo): el filtro
``store_id`` de la lectura es la unica guarda entre tiendas.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditAction, AuditLog
from modules.users.model import User


class AuditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(
        self,
        *,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        store_id: str,
        actor: User | None = None,
        payload_before: dict[str, Any] | None = None,
        payload_after: dict[str, Any] | None = None,
        context: str | None = None,
    ) -> None:
        """
        Inserta un registro de auditoría.

        No hace commit por sí mismo: el commit lo realiza el servicio
        de negocio que encapsula toda la operación atómica. ``store_id`` es
        obligatorio (B5-12): es la tienda del recurso auditado y lo que
        permite leer la fila acotada a la tienda; antes quedaba NULL.
        """
        entry = AuditLog(
            actor_id=actor.id if actor else None,
            actor_public_id=actor.public_id if actor else None,
            actor_email=actor.email if actor else None,
            resource_type=resource_type,
            resource_id=resource_id,
            store_id=store_id,
            action=action.value,
            payload_before=payload_before,
            payload_after=payload_after,
            context=context,
        )
        self.db.add(entry)
        # No hacer flush aquí: se escribe en el mismo commit del servicio

    async def list_store_resource_logs(
        self,
        *,
        store_id: str,
        resource_types: tuple[str, ...],
        limit: int,
        offset: int,
        resource_id: str | None = None,
    ) -> list[AuditLog]:
        """Auditoria de ``resource_types`` de UNA tienda, mas reciente primero.

        ``store_id`` en el ``WHERE`` es la guarda entre tiendas (la tabla no
        tiene RLS). ``LIMIT``/``OFFSET`` en la base, no en Python.
        """
        query = select(AuditLog).where(
            AuditLog.store_id == store_id,
            AuditLog.resource_type.in_(resource_types),
        )
        if resource_id is not None:
            query = query.where(AuditLog.resource_id == resource_id)
        result = await self.db.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
