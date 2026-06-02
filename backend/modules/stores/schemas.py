from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, List

from core.business_types import BusinessType, DEFAULT_BUSINESS_TYPE
from core.validation import SLUG_PATTERN, reject_unsafe_url

class BusinessHourPeriod(BaseModel):
    open: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    close: str = Field(..., pattern=r"^\d{2}:\d{2}$")

class StoreUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    slug: Optional[str] = Field(None, max_length=100, pattern=SLUG_PATTERN)
    business_type: Optional[BusinessType] = None
    logo_url: Optional[str] = Field(None, max_length=500)
    primary_color: Optional[str] = Field(None, max_length=20)
    cover_url: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = Field(None, max_length=2000)
    whatsapp_number: Optional[str] = Field(None, max_length=50)
    instagram_url: Optional[str] = Field(None, max_length=500)
    facebook_url: Optional[str] = Field(None, max_length=500)
    website_url: Optional[str] = Field(None, max_length=500)
    
    cancellation_hours: Optional[int] = Field(None, ge=0)
    buffer_minutes: Optional[int] = Field(None, ge=0)
    
    business_hours: Optional[Dict[str, List[BusinessHourPeriod]]] = Field(None, max_length=7)
    
    send_email_confirmation: Optional[bool] = None
    send_email_reminders: Optional[bool] = None

    @field_validator("logo_url", "cover_url", "instagram_url", "facebook_url", "website_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)


class StoreFeatureFlags(BaseModel):
    payments: bool = False
    ledger: bool = False
    advanced_reports: bool = False
    new_calendar: bool = False
    otp_booking: bool = False


class StoreFeatureFlagsUpdate(BaseModel):
    payments: bool | None = None
    ledger: bool | None = None
    advanced_reports: bool | None = None
    new_calendar: bool | None = None
    otp_booking: bool | None = None


class StoreFeatureFlagsResponse(BaseModel):
    flags: StoreFeatureFlags

class StoreResponse(BaseModel):
    public_id: str
    name: str
    slug: str
    business_type: BusinessType = DEFAULT_BUSINESS_TYPE
    logo_url: Optional[str]
    primary_color: str
    cover_url: Optional[str] = None
    description: Optional[str] = None
    whatsapp_number: Optional[str] = None
    instagram_url: Optional[str] = None
    facebook_url: Optional[str] = None
    website_url: Optional[str] = None
    cancellation_hours: int
    buffer_minutes: int
    business_hours: Dict[str, List[BusinessHourPeriod]]
    send_email_confirmation: bool
    send_email_reminders: bool
    feature_flags: StoreFeatureFlags

    class Config:
        from_attributes = True
