from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from core.validation import validate_password_strength
from modules.users.model import UserRole


class UserBase(BaseModel):
    email: EmailStr
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)
    role: UserRole = UserRole.STAFF


class UserCreate(UserBase):
    password: str = Field(..., min_length=12, max_length=128)

    _validar_password = field_validator("password")(validate_password_strength)


class UserUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)
    role: UserRole | None = None
    password: str | None = Field(None, min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def _validar_password(cls, value: str | None) -> str | None:
        # En el update el password es opcional: solo se valida si viene.
        return validate_password_strength(value) if value else value

    is_active: bool | None = None


class UserResponse(UserBase):
    public_id: str
    is_active: bool
    is_global_admin: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
