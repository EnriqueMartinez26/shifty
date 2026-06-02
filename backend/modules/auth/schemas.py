from pydantic import BaseModel, EmailStr, Field

from core.business_types import BusinessType, DEFAULT_BUSINESS_TYPE
from core.validation import SLUG_PATTERN

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=128)


class ResetPasswordResponse(BaseModel):
    message: str

class StoreRegisterRequest(BaseModel):
    # Datos de la Tienda
    store_name: str = Field(..., min_length=2, max_length=255)
    store_slug: str = Field(..., min_length=2, max_length=100, pattern=SLUG_PATTERN)
    business_type: BusinessType = DEFAULT_BUSINESS_TYPE
    
    # Datos del Administrador
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8, max_length=128)
    admin_first_name: str = Field(..., min_length=1, max_length=100)
    admin_last_name: str = Field(..., min_length=1, max_length=100)

class UserResponse(BaseModel):
    public_id: str
    email: EmailStr
    first_name: str | None
    last_name: str | None
    role: str

class RegistrationResponse(BaseModel):
    store_public_id: str
    admin: UserResponse

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
