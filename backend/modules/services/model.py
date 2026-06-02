from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity
import ulid


class Service(BaseEntity):
    __tablename__ = "services"

    public_id: Mapped[str] = mapped_column(
        String(26),
        unique=True,
        default=lambda: str(ulid.ULID()),
        index=True,
    )
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    deposit_mode: Mapped[str] = mapped_column(String(20), default="none")
    deposit_type: Mapped[str] = mapped_column(String(20), default="percent")
    deposit_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20))
    youtube_trailer_url: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint("deposit_mode IN ('none', 'optional', 'required')", name="ck_services_deposit_mode"),
        CheckConstraint("deposit_type IN ('percent', 'fixed', 'full')", name="ck_services_deposit_type"),
    )
