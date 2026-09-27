from datetime import datetime, timezone
from typing import Any

import ulid
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


def _split_full_name(full_name: str | None) -> tuple[str | None, str | None]:
    value = (full_name or "").strip()
    if not value:
        return None, None
    parts = value.split(maxsplit=1)
    first_name = parts[0].strip() if parts else None
    last_name = parts[1].strip() if len(parts) > 1 else None
    return first_name or None, last_name or None


class UserModel(Base):
    __tablename__ = "users"
    # Un telefono identifica a UN cliente por tienda. Dos filas iguales
    # rompian get_or_create_client con MultipleResultsFound (500); el
    # repositorio ya elige la mas reciente, y este indice impide que vuelvan
    # a aparecer. Solo clientes: el personal comparte telefonos del local.
    #
    # El email se guarda normalizado (minusculas) y ck_users_email_lower lo
    # exige en la base (F1-12, migraciones c4e6a8b0d2f1 + d5f7b9c1e3a2): el
    # login lo busca por IGUALDAD sobre la columna, que bajo RLS usa
    # ix_users_email (lower() no es leakproof y recorria la tabla entera).
    #
    # PV-01 (2026-09-25, decision de Mateo): el email de un CLIENTE es unico
    # por tienda (uq_users_client_email_per_store); el de quien inicia sesion
    # (personal, admins, superadmin) sigue unico en toda la plataforma
    # (uq_users_email_non_client). Un cliente y un profesional pueden
    # compartir email, asi que toda busqueda de login filtra role <> 'client'
    # y nunca ve dos filas. Con el CHECK de minusculas los dos indices valen
    # sin importar mayusculas: el funcional uq_users_email_lower (global) se
    # retiro en la misma migracion, 4b6d8f0a2c13.
    __table_args__ = (
        Index(
            "uq_users_client_phone_per_store",
            "store_id",
            "phone",
            unique=True,
            postgresql_where=text("role = 'client' AND phone IS NOT NULL"),
            sqlite_where=text("role = 'client' AND phone IS NOT NULL"),
        ),
        Index(
            "uq_users_client_email_per_store",
            "store_id",
            "email",
            unique=True,
            postgresql_where=text("role = 'client'"),
            sqlite_where=text("role = 'client'"),
        ),
        Index(
            "uq_users_email_non_client",
            "email",
            unique=True,
            postgresql_where=text("role <> 'client'"),
            sqlite_where=text("role <> 'client'"),
        ),
        CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(ulid.ULID())
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str] = mapped_column(String(50))
    store_id: Mapped[str] = mapped_column(String, index=True)
    is_global_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_reset_token_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __init__(self, **kwargs: Any) -> None:
        full_name = kwargs.pop("full_name", None)
        super().__init__(**kwargs)
        if full_name:
            self.full_name = full_name

    @property
    def full_name(self) -> str:
        value = " ".join(
            part.strip()
            for part in (self.first_name, self.last_name)
            if part and part.strip()
        ).strip()
        if value:
            return value
        override = getattr(self, "_full_name_override", "")
        return override or ""

    @full_name.setter
    def full_name(self, value: str | None) -> None:
        first_name, last_name = _split_full_name(value)
        if first_name is not None:
            self.first_name = first_name
        if last_name is not None:
            self.last_name = last_name
        self._full_name_override = (value or "").strip()

    @property
    def public_id(self) -> str:
        return self.id
