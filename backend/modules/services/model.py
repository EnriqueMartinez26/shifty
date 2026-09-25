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
    image_url: Mapped[str | None] = mapped_column(String(500))
    youtube_trailer_url: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint(
            "deposit_mode IN ('none', 'optional', 'required')",
            name="ck_services_deposit_mode",
        ),
        CheckConstraint(
            "deposit_type IN ('percent', 'fixed', 'full')",
            name="ck_services_deposit_type",
        ),
        # La terna de sena se validaba SOLO en la entrada (Pydantic). Lo que
        # toca dinero se garantiza en la base: estos dos CHECK son el mismo
        # criterio que `deposit_policy_error`, para las filas que no pasan por
        # el schema (migraciones, carga directa, dos PATCH concurrentes que
        # validan cada uno contra el snapshot que leyo sin lock).
        # AUD2-B6-03, 2026-09-20.
        CheckConstraint(
            "deposit_mode = 'none' OR deposit_type = 'full' "
            "OR (deposit_amount IS NOT NULL AND deposit_amount > 0)",
            name="ck_services_deposit_amount_presente",
        ),
        CheckConstraint(
            "deposit_type <> 'percent' OR deposit_amount IS NULL "
            "OR deposit_amount <= 100",
            name="ck_services_deposit_percent_max",
        ),
        # El tope del producto es 480 minutos (schemas.py); la base garantiza
        # un dia, que es lo que sostiene la cota inferior del solapamiento
        # (F1-13, ck_appointments_max_span; migraciones c3d5e7f9a1b4 +
        # d4e6f8a0b2c5).
        CheckConstraint("duration_minutes <= 1440", name="ck_services_duration_max"),
    )
