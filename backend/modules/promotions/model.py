from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class PromotionType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"


class StorePromotion(BaseEntity):
    __tablename__ = "store_promotions"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    code: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    promotion_type: Mapped[str] = mapped_column(
        String(20), default=PromotionType.PERCENT.value
    )
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    min_service_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_uses: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("store_id", "code", name="uq_store_promotions_store_code"),
        CheckConstraint(
            "promotion_type IN ('percent', 'fixed')", name="ck_store_promotions_type"
        ),
        CheckConstraint("value > 0", name="ck_store_promotions_value_positive"),
        CheckConstraint(
            "min_service_amount IS NULL OR min_service_amount >= 0",
            name="ck_store_promotions_min_amount_non_negative",
        ),
        CheckConstraint(
            "max_uses IS NULL OR max_uses > 0",
            name="ck_store_promotions_max_uses_positive",
        ),
        CheckConstraint(
            "current_uses >= 0", name="ck_store_promotions_current_uses_non_negative"
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_from < valid_until",
            name="ck_store_promotions_valid_window",
        ),
    )


class PromotionRedemption(BaseEntity):
    __tablename__ = "promotion_redemptions"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    promotion_id: Mapped[str] = mapped_column(
        ForeignKey("store_promotions.id"), index=True
    )
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id"), index=True
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    code_snapshot: Mapped[str] = mapped_column(String(50))
    title_snapshot: Mapped[str] = mapped_column(String(120))
    promotion_type_snapshot: Mapped[str] = mapped_column(String(20))
    value_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    final_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    __table_args__ = (
        UniqueConstraint(
            "promotion_id",
            "appointment_id",
            name="uq_promotion_redemptions_promotion_appointment",
        ),
        CheckConstraint(
            "promotion_type_snapshot IN ('percent', 'fixed')",
            name="ck_promotion_redemptions_type",
        ),
        CheckConstraint(
            "base_amount >= 0", name="ck_promotion_redemptions_base_non_negative"
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="ck_promotion_redemptions_discount_non_negative",
        ),
        CheckConstraint(
            "final_amount >= 0", name="ck_promotion_redemptions_final_non_negative"
        ),
    )
