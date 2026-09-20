from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from core.validation import reject_control_chars, validate_password_strength
from modules.users.model import UserRole

# AUD2-B5-03: nombre y apellido eran el unico texto libre del sistema sin esta
# guarda (staff, services, stores, superadmin y public_api ya la tienen). Salen
# al reporte del dueno via _report_client_name, asi que un NUL o un bidi
# cargado desde /users llegaba hasta la planilla (regla 19).
_NOMBRES_LIBRES = ("first_name", "last_name")


class UserBase(BaseModel):
    email: EmailStr
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)
    role: UserRole = UserRole.STAFF

    @field_validator(*_NOMBRES_LIBRES)
    @classmethod
    def reject_control_chars_in_name(cls, value: str | None) -> str | None:
        return reject_control_chars(value)


class UserCreate(UserBase):
    password: str = Field(..., min_length=12, max_length=128)

    _validar_password = field_validator("password")(validate_password_strength)


class UserUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)
    role: UserRole | None = None
    password: str | None = Field(None, min_length=12, max_length=128)

    @field_validator(*_NOMBRES_LIBRES)
    @classmethod
    def reject_control_chars_in_name(cls, value: str | None) -> str | None:
        return reject_control_chars(value)

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
