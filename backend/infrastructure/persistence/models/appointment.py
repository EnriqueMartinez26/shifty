from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

import ulid
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.models.base import Base

if TYPE_CHECKING:
    from modules.appointments.model import AppointmentStatus


# Tope de duracion de un turno EN LA BASE: ``ck_appointments_max_span``
# (``ends_at <= starts_at + interval '1 day'``, migraciones e9f1b3d5a7c0 +
# f0a2c4e6b8d1; decision 15 del plan de rendimiento). El tope real del
# producto es 480 minutos (``services/schemas.py``); este es holgado a
# proposito. Lo que sostiene es la cota inferior de toda consulta de
# solapamiento (``appointments.repository.active_appointment_overlap``): un
# turno que termina despues de ``inicio`` empezo despues de
# ``inicio - MAX_APPOINTMENT_SPAN``, y con esa cota el indice
# ``(store_id, staff_id, starts_at)`` recorre solo la ventana y no toda la
# historia del profesional (F1-13, R7-02). No se declara como CheckConstraint
# del modelo porque SQLite (la suite de integracion) no tiene ``interval``.
MAX_APPOINTMENT_SPAN = timedelta(days=1)


# Unica fuente de verdad del grafo de transiciones del turno.
# Los estados terminales mapean a conjuntos vacios: son absorbentes.
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled", "pending_payment", "expired"},
    "pending_payment": {"confirmed", "cancelled", "expired"},
    "confirmed": {"completed", "cancelled", "absent"},
    "cancelled": set(),
    "completed": set(),
    "absent": set(),
    "expired": set(),
}


class AppointmentModel(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(ulid.ULID())
    )
    service_id: Mapped[str] = mapped_column(
        String, ForeignKey("services.id"), index=True
    )
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.id"), index=True)
    store_id: Mapped[str] = mapped_column(String, ForeignKey("stores.id"))
    client_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), index=True
    )
    # Snapshot de contacto congelado al reservar: no se re-deriva del
    # usuario vinculado despues. Si el cliente cambia nombre/email/telefono,
    # el turno ya reservado conserva lo que valia al momento de la reserva.
    client_name: Mapped[str] = mapped_column(String(255))
    client_email: Mapped[Optional[str]] = mapped_column(String(255))
    client_phone: Mapped[Optional[str]] = mapped_column(String(50))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column()
    # Precio congelado al momento de reservar (precio de lista de ese momento).
    # El precio del servicio puede cambiar despues; el turno tiene que valer lo
    # que valia cuando se reservo, no lo que sale hoy. Es el monto que se cobra
    # y el que usa el reporte de ingresos. Nullable por los turnos historicos
    # anteriores a esta columna.
    price_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    # Adicionales elegidos al reservar (decision de Mateo, 2026-10-14): suman
    # precio, nunca tiempo. ``price_amount`` es el TOTAL congelado: servicio
    # + adicionales, con la promo aplicada a esa suma (decision de Mateo,
    # 2026-10-15). ``addons_amount`` es la suma SIN descuento de las lineas
    # de ``addons_snapshot`` (``[{addon_id, name, unit_price, quantity,
    # amount}]``, importes como texto): editar o borrar un adicional no
    # cambia un turno ya tomado. ``ck_appointments_addons_amount``
    # (migraciones e2a4c6e8f0b1 + f3b5d7f9a1c2) exige que ni los adicionales
    # ni el total sean negativos, pero NO que el total supere a los
    # adicionales: con un descuento grande el total puede quedar por debajo.
    addons_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0"),
    )
    addons_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    # Varios servicios del mismo profesional en UN turno (decision de Mateo,
    # 2026-10-16): ``service_id`` es el principal (el primero elegido) y estos
    # congelan los demas. ``extra_services_snapshot`` es ``[{service_id,
    # public_id, name, duration_minutes, price}]`` (precio como texto) o NULL
    # en un turno de un solo servicio; ``extra_services_amount`` es la suma
    # SIN descuento de esos precios. ``duration_minutes``/``ends_at`` y
    # ``price_amount`` ya son el total. Migraciones b8d0f2a4c6e1 +
    # c9e1a3b5d7f2 (``ck_appointments_extra_services_amount``).
    extra_services_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0"),
    )
    extra_services_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    # Columna privada: la unica escritura legitima es apply_status_transition().
    # Se expone como hybrid_property de solo lectura, asi que
    # `appointment.status = "completed"` levanta AttributeError en vez de
    # saltearse el grafo. A nivel clase sigue sirviendo para filtrar en queries.
    _status: Mapped[str] = mapped_column("status", String(50), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    notes_staff: Mapped[Optional[str]] = mapped_column(Text)
    intake_answers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )
    # Momento en que el cliente acepto los terminos y la politica de sena de la
    # tienda. Queda registrado como respaldo ante un reclamo.
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Versiones de los terminos y de la politica de privacidad que acepto
    # (PV-09, 2026-09-25). NULL si el portal no las mando o si el turno lo
    # cargo el panel (el personal no es el cliente dando su consentimiento).
    terms_version: Mapped[Optional[str]] = mapped_column(String(20))
    privacy_version: Mapped[Optional[str]] = mapped_column(String(20))
    # Marcas durables de recordatorio. El job las reclama con
    # ``UPDATE ... WHERE col IS NULL`` (seguro entre workers) y las deja en
    # nulo si el envio falla. Reprogramar crea un turno nuevo, asi que el
    # movido arranca sin marcas.
    reminder_24h_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    reminder_2h_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    # Optimistic locking: SQLAlchemy incrementa esta columna en cada UPDATE y
    # falla con StaleDataError si otra transaccion la movio mientras tanto.
    # Es la red donde el lock pesimista no llega.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    service = relationship("Service")
    staff = relationship("StaffModel")
    client = relationship("UserModel")

    def __init__(self, **kwargs: Any) -> None:
        # `status=` es el nombre publico que usan los repositorios al crear.
        if "status" in kwargs:
            kwargs["_status"] = kwargs.pop("status")
        super().__init__(**kwargs)

    @hybrid_property
    def status(self) -> str:
        return self._status

    @status.inplace.expression
    @classmethod
    def _status_expression(cls) -> Mapped[str]:
        return cls._status

    @property
    def public_id(self) -> str:
        return self.id

    def apply_status_transition(self, new_status: AppointmentStatus | str) -> None:
        from core.exceptions import InvalidStatusTransitionException

        attempted = (
            new_status.value if hasattr(new_status, "value") else str(new_status)
        )
        current = self.status

        if attempted == current:
            return

        if attempted not in ALLOWED_STATUS_TRANSITIONS.get(current, set()):
            raise InvalidStatusTransitionException(current=current, attempted=attempted)

        self._status = attempted
        now = datetime.now(timezone.utc)
        if attempted == "cancelled":
            self.cancelled_at = now
        elif attempted == "completed":
            self.completed_at = now
        self.updated_at = now

    __mapper_args__ = {"version_id_col": version}

    # La tabla lleva ``fillfactor = 90`` (F1-15, migracion b7d9f1a3c5e8): deja
    # lugar en la pagina para UPDATE HOT. Vive solo en la migracion porque el
    # modelo no declara parametros de almacenamiento.
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'pending_payment', 'confirmed', 'absent', 'completed', 'cancelled', 'expired')",
            name="check_appointment_status_v3",
        ),
        CheckConstraint(
            "addons_amount >= 0 AND (price_amount IS NULL OR price_amount >= 0)",
            name="ck_appointments_addons_amount",
        ),
        CheckConstraint(
            "extra_services_amount >= 0",
            name="ck_appointments_extra_services_amount",
        ),
        # Retenciones vivas para el job de vencimiento (cada minuto):
        # ``expires_at`` nunca se limpia y el indice plano barria todas las
        # retenciones viejas ya resueltas (F1-14, migracion a6c8e0f2b4d7). El
        # predicado es el de ``payments/jobs.py::_expired_holds_query``.
        Index(
            "ix_appointments_hold_expiry",
            "expires_at",
            postgresql_where=text(
                "status IN ('pending', 'pending_payment') AND expires_at IS NOT NULL"
            ),
            sqlite_where=text(
                "status IN ('pending', 'pending_payment') AND expires_at IS NOT NULL"
            ),
        ),
    )
