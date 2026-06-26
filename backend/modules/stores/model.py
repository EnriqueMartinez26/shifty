from datetime import time
from typing import Any

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String,
    JSON,
    Integer,
    Boolean,
    ForeignKey,
    Time,
    UniqueConstraint,
    CheckConstraint,
)

from core.business_types import BusinessType, normalize_business_type
from core.feature_flags import normalize_store_feature_flags
from core.models import BaseEntity
import ulid

ThemeConfig = dict[str, Any]
FeatureFlags = dict[str, bool]
BusinessHoursPeriod = dict[str, str]
BusinessHours = dict[str, list[BusinessHoursPeriod]]
CustomClientFieldData = dict[str, Any]


class StoreSchedule(BaseEntity):
    __tablename__ = "store_schedules"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    open_time: Mapped[time] = mapped_column(Time)
    close_time: Mapped[time] = mapped_column(Time)

    store: Mapped["Store"] = relationship(back_populates="schedules")

    __table_args__ = (
        UniqueConstraint("store_id", "day_of_week", name="uq_store_day_schedule"),
        CheckConstraint("open_time < close_time", name="check_store_schedule_times"),
    )


class Store(BaseEntity):
    __tablename__ = "stores"

    public_id: Mapped[str] = mapped_column(
        String(26), unique=True, default=lambda: str(ulid.ULID()), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    primary_color: Mapped[str] = mapped_column(String(20), default="#000000")

    requires_deposit: Mapped[bool] = mapped_column(Boolean, default=False)
    deposit_percentage: Mapped[int] = mapped_column(Integer, default=0)
    cancellation_hours: Mapped[int] = mapped_column(Integer, default=24)
    min_booking_notice_hours: Mapped[int] = mapped_column(Integer, default=2)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)

    schedules: Mapped[list["StoreSchedule"]] = relationship(
        back_populates="store", cascade="all, delete-orphan", lazy="selectin"
    )

    send_email_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    send_email_reminders: Mapped[bool] = mapped_column(Boolean, default=True)

    theme_config: Mapped[ThemeConfig] = mapped_column(JSON, default=dict)
    feature_flags: Mapped[FeatureFlags] = mapped_column(JSON, default=dict)

    @property
    def business_hours(self) -> BusinessHours:
        hours: BusinessHours = {
            "mon": [],
            "tue": [],
            "wed": [],
            "thu": [],
            "fri": [],
            "sat": [],
            "sun": [],
        }
        days_map = {
            0: "mon",
            1: "tue",
            2: "wed",
            3: "thu",
            4: "fri",
            5: "sat",
            6: "sun",
        }
        if not getattr(self, "schedules", None):
            return hours
        for schedule in self.schedules:
            if schedule.open_time and schedule.close_time:
                hours[days_map[schedule.day_of_week]].append(
                    {
                        "open": schedule.open_time.strftime("%H:%M"),
                        "close": schedule.close_time.strftime("%H:%M"),
                    }
                )
        return hours

    @property
    def cover_url(self) -> str | None:
        return (self.theme_config or {}).get("cover_url")

    @property
    def description(self) -> str | None:
        return (self.theme_config or {}).get("description")

    @property
    def whatsapp_number(self) -> str | None:
        return (self.theme_config or {}).get("whatsapp_number")

    @property
    def instagram_url(self) -> str | None:
        return (self.theme_config or {}).get("instagram_url")

    @property
    def facebook_url(self) -> str | None:
        return (self.theme_config or {}).get("facebook_url")

    @property
    def website_url(self) -> str | None:
        return (self.theme_config or {}).get("website_url")

    @property
    def business_type(self) -> BusinessType:
        return normalize_business_type((self.theme_config or {}).get("business_type"))

    @property
    def custom_client_fields(self) -> list[CustomClientFieldData]:
        return (self.theme_config or {}).get("custom_client_fields") or []

    @property
    def normalized_feature_flags(self) -> FeatureFlags:
        return normalize_store_feature_flags(self.feature_flags)
