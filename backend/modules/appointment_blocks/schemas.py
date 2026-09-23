from datetime import datetime, timedelta

from pydantic import BaseModel, Field, model_validator

from core.utils import ensure_utc_aware
from core.validation import reject_payload_control_chars

# Tope de duracion de UN rango de bloqueo (AUD2-B1-10). Regla 9 aplicada a
# una duracion: sin cota superior, un bloqueo de 2026 a 2036 era valido y la
# invalidacion del cache recorria ~3650 dias con un INCR + EXPIRE por cada
# uno, sobre el mismo Redis que sostiene el rate limit y la idempotencia de
# cobros. Un anio entero (con bisiesto) cubre una licencia larga.
MAX_BLOCK_DURATION = timedelta(days=366)


def block_range_error(starts_at: datetime, ends_at: datetime) -> str | None:
    """Motivo por el que un rango de bloqueo no vale, o None si vale.

    Una sola regla para los schemas de entrada y para el PATCH del service,
    que decide sobre el rango que dejaria el cambio (puede venir un solo
    extremo). Un instante naive se toma como UTC, igual que en el resto del
    modulo.
    """
    inicio = ensure_utc_aware(starts_at)
    fin = ensure_utc_aware(ends_at)
    if inicio >= fin:
        return "El inicio debe ser anterior al fin"
    if fin - inicio > MAX_BLOCK_DURATION:
        return f"Un bloqueo no puede durar mas de {MAX_BLOCK_DURATION.days} dias"
    return None


class AppointmentBlockBase(BaseModel):
    staff_id: str = Field(..., min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    reason: str = Field("No atender", max_length=255)

    @model_validator(mode="after")
    def validate_range(self) -> "AppointmentBlockBase":
        error = block_range_error(self.starts_at, self.ends_at)
        if error:
            raise ValueError(error)
        return self

    @model_validator(mode="after")
    def reject_control_chars_in_reason(self) -> "AppointmentBlockBase":
        # El motivo lo tipea un admin, pero se PUBLICA: sale como motivo del
        # slot en la disponibilidad, en el listado del panel y en el cuerpo
        # del mail de cancelacion en bloque (regla 19: "texto que se publica",
        # sin importar quien lo tipeo). Se valida al escribir, igual que la
        # tienda y el personal: una fila legada con un invisible se sigue
        # leyendo.
        self.reason = reject_payload_control_chars(self.reason) or ""
        return self


class StoreWideBlockCreate(BaseModel):
    """Cierre de toda la tienda: un feriado, una mudanza, un dia de limpieza.

    Sin esto habia que bloquear a cada profesional uno por uno, y con cinco
    empleados cerrar un dia eran cinco operaciones.
    """

    starts_at: datetime
    ends_at: datetime
    reason: str = Field("Cerrado", max_length=255)
    # Si hay turnos reservados adentro, sin este flag el alta responde 409 con
    # la cantidad; con el flag (solo administradores) se cancelan los que se
    # pueden y se avisa al cliente por mail.
    cancel_affected: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "StoreWideBlockCreate":
        error = block_range_error(self.starts_at, self.ends_at)
        if error:
            raise ValueError(error)
        return self

    @model_validator(mode="after")
    def reject_control_chars_in_reason(self) -> "StoreWideBlockCreate":
        self.reason = reject_payload_control_chars(self.reason) or ""
        return self


class StoreWideBlockResponse(BaseModel):
    """Resultado del cierre: a cuantos profesionales alcanzo."""

    blocked_staff: int
    starts_at: datetime
    ends_at: datetime
    reason: str


class AppointmentBlockCreate(AppointmentBlockBase):
    cancel_affected: bool = False


class RecurringAppointmentBlockCreate(AppointmentBlockBase):
    recurrence: str = Field(default="none", pattern=r"^(none|daily|weekly)$")
    recurrence_until: datetime | None = None
    max_occurrences: int = Field(default=30, ge=1, le=120)
    cancel_affected: bool = False

    @model_validator(mode="after")
    def validate_recurrence(self) -> "RecurringAppointmentBlockCreate":
        if self.recurrence != "none" and self.recurrence_until is None:
            raise ValueError(
                "recurrence_until es obligatorio cuando recurrence no es none"
            )
        if self.recurrence_until and self.recurrence_until <= self.starts_at:
            raise ValueError("recurrence_until debe ser posterior al inicio")
        return self


class AppointmentBlockUpdate(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    # Si el bloqueo pasa a cubrir turnos reservados (moverlo, agrandarlo,
    # reactivarlo), sin este flag el PATCH responde 409 con la cantidad; con
    # el flag (solo administradores) se cancelan los que se pueden y se avisa
    # al cliente. Mismo contrato que el alta (AUD2-B1-01).
    cancel_affected: bool = False

    @model_validator(mode="after")
    def reject_control_chars_in_reason(self) -> "AppointmentBlockUpdate":
        self.reason = reject_payload_control_chars(self.reason)
        return self


class AppointmentBlockResponse(BaseModel):
    public_id: str
    staff_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str
    is_active: bool

    class Config:
        from_attributes = True


class AppointmentBlockBatchResponse(BaseModel):
    created: int
    blocks: list[AppointmentBlockResponse]


class BlockTemplateResponse(BaseModel):
    key: str
    label: str
    reason: str


class BlockPreviewRequest(BaseModel):
    """Que turnos caerian dentro de un bloqueo (sin escribir nada).

    ``staff_id`` en null significa toda la tienda (cierre).
    """

    staff_id: str | None = Field(None, min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    recurrence: str = Field(default="none", pattern=r"^(none|daily|weekly)$")
    recurrence_until: datetime | None = None
    max_occurrences: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_ranges(self) -> "BlockPreviewRequest":
        error = block_range_error(self.starts_at, self.ends_at)
        if error:
            raise ValueError(error)
        if self.recurrence != "none" and self.recurrence_until is None:
            raise ValueError(
                "recurrence_until es obligatorio cuando recurrence no es none"
            )
        if self.recurrence_until and self.recurrence_until <= self.starts_at:
            raise ValueError("recurrence_until debe ser posterior al inicio")
        return self


class AffectedAppointmentResponse(BaseModel):
    public_id: str
    client_name: str
    client_phone: str | None = None
    service_name: str
    staff_name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    # None = se cancela con cancel_affected; "pending_payment" = esperando la
    # sena en Mercado Pago (liberar a mano); "has_deposit" = sena acreditada
    # (decision del dueno).
    blocker: str | None = None
    cancellable: bool


class BlockPreviewResponse(BaseModel):
    ranges: int
    affected: list[AffectedAppointmentResponse]
