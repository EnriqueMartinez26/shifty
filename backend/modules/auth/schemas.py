from pydantic import BaseModel, EmailStr, Field, field_validator

from core.business_types import BusinessType, DEFAULT_BUSINESS_TYPE
from core.validation import SLUG_PATTERN, validate_password_strength


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    # Sin minimo a proposito: la politica aplica al CREAR claves; en el login,
    # una clave corta debe dar 401 generico, no un 422 que revela la politica.
    password: str = Field(..., min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)
    new_password: str = Field(..., min_length=12, max_length=128)

    _validar_password = field_validator("new_password")(validate_password_strength)


class ResetPasswordResponse(BaseModel):
    message: str


class StoreRegisterRequest(BaseModel):
    # Datos de la Tienda
    store_name: str = Field(..., min_length=2, max_length=255)
    store_slug: str = Field(..., min_length=2, max_length=100, pattern=SLUG_PATTERN)
    business_type: BusinessType = DEFAULT_BUSINESS_TYPE

    # Datos del Administrador
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=12, max_length=128)
    admin_first_name: str = Field(..., min_length=1, max_length=100)
    admin_last_name: str = Field(..., min_length=1, max_length=100)

    _validar_password = field_validator("admin_password")(validate_password_strength)


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
    # La actual sin minimo: puede ser legacy mas corta que la politica vigente.
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)

    _validar_password = field_validator("new_password")(validate_password_strength)


class LogoutRequest(BaseModel):
    """Para clientes sin cookie (movil/CLI) que guardaron el refresh token."""

    refresh_token: str | None = Field(None, min_length=20, max_length=256)


class SessionItem(BaseModel):
    session_id: str
    created_at: str
    expires_at: str
    user_agent: str | None
    ip_address: str | None
    current: bool


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]
