from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class Plan(BaseEntity):
    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="ARS")
    billing_interval: Mapped[str] = mapped_column(String(20), default="monthly")
    max_staff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_services: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def public_id(self) -> str:
        return self.id


class SaaSCoupon(BaseEntity):
    __tablename__ = "saas_coupons"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    coupon_type: Mapped[str] = mapped_column(String(20))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_uses: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    one_time_per_store: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    @property
    def public_id(self) -> str:
        return self.id


class StoreSubscription(BaseEntity):
    __tablename__ = "store_subscriptions"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), index=True)
    # Copia del nombre del plan: la tabla plans es solo para superadmin en RLS
    # y el dueno de la tienda necesita ver que plan tiene.
    plan_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Grafo en modules/billing/subscription_rules.py + CHECK en la base.
    status: Mapped[str] = mapped_column(String(30), default="active")
    # Aviso de vencimiento ya enviado para este periodo (idempotencia del job).
    expiry_warning_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="ARS")
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    coupon_id: Mapped[str | None] = mapped_column(
        ForeignKey("saas_coupons.id"), nullable=True, index=True
    )
    billing_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'past_due', 'suspended', 'cancelled')",
            name="ck_store_subscriptions_status",
        ),
    )

    @property
    def public_id(self) -> str:
        return self.id


class CouponRedemption(BaseEntity):
    __tablename__ = "coupon_redemptions"

    coupon_id: Mapped[str] = mapped_column(ForeignKey("saas_coupons.id"), index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("store_subscriptions.id"), nullable=True, index=True
    )
    redeemed_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    code_snapshot: Mapped[str] = mapped_column(String(50))
    coupon_type_snapshot: Mapped[str] = mapped_column(String(20))
    value_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    final_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10))
    redemption_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    @property
    def public_id(self) -> str:
        return self.id
