from pydantic import BaseModel, EmailStr, Field, field_validator

from core.validation import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    validate_password_strength,
)


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
    new_password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )

    _validar_password = field_validator("new_password")(validate_password_strength)


class ResetPasswordResponse(BaseModel):
    message: str


class ChangePasswordRequest(BaseModel):
    # La actual sin minimo: puede ser legacy mas corta que la politica vigente.
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )

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


class CurrentUserResponse(BaseModel):
    """Respuesta de ``GET /me``.

    Todo sale del usuario que ``get_current_user`` relee de la base en cada
    request, nunca de los claims del token (regla 1): un cambio de nombre se ve
    en el proximo ``/me`` sin volver a iniciar sesion. ``first_name`` y
    ``last_name`` son aditivos (2026-10-14): sin ellos el panel no podia
    proponer el nombre visible de "Agregarme como profesional".
    """

    email: str
    role: str
    store_id: str | None
    public_id: str
    is_global_admin: bool
    first_name: str | None
    last_name: str | None
