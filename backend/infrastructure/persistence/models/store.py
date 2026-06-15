from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.models.base import Base
import ulid


class StoreModel(Base):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    public_id: Mapped[str] = mapped_column(
        String(26), unique=True, index=True, default=lambda: str(ulid.ULID())
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(20), default="#000000")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Business Rules
    requires_deposit: Mapped[bool] = mapped_column(Boolean, default=False)
    deposit_percentage: Mapped[int] = mapped_column(Integer, default=0)
    cancellation_hours: Mapped[int] = mapped_column(Integer, default=24)
    min_booking_notice_hours: Mapped[int] = mapped_column(Integer, default=2)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)

    # Notifications
    send_email_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    send_email_reminders: Mapped[bool] = mapped_column(Boolean, default=True)

    theme_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
