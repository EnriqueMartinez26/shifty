from datetime import datetime, timezone

import ulid
from sqlalchemy import Boolean, DateTime, String
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

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(ulid.ULID())
    )
    email: Mapped[str] = mapped_column(String(255), index=True, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
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

    def __init__(self, **kwargs):
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
