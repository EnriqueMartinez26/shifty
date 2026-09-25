from datetime import datetime, timezone
from decimal import Decimal
import enum
from typing import Any, TypeAlias

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]

# Reintentos antes de dar por perdido un webhook que no pudimos resolver.
WEBHOOK_INBOX_MAX_ATTEMPTS = 10


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    MANUAL_CONFIRMED = "manual_confirmed"


# Estados en los que la plata efectivamente entro. Unica fuente: la leen
# ``Payment.is_accredited`` y las consultas que filtran en SQL (la guarda de
# reprogramacion del cliente, ``PublicRepository.accredited_appointment_ids``).
ACCREDITED_PAYMENT_STATUSES: frozenset[str] = frozenset(
    {PaymentStatus.APPROVED.value, PaymentStatus.MANUAL_CONFIRMED.value}
)

# Cobro VIVO: el cobro del turno sigue abierto y su link se puede pagar (o
# el panel lo puede volver a generar sin tocar el turno). Decision del dueno
# (2026-09-25, D1): un turno con cobro vivo no lo cancela ni lo reprograma el
# cliente, y cancelarlo desde el panel vence el cobro en la misma transaccion.
# Unica fuente: la leen ``Payment.is_live_charge`` y las consultas en SQL
# (``payments.repository.live_charge_of``). ``rejected`` SI es vivo: tras un
# rechazo Mercado Pago deja reintentar sobre la misma preferencia (revision de
# perf/f4-pay, 2026-09-25); el panel lo vence por ``rejected -> expired``, que
# ya esta en el grafo. ``expired`` no es vivo (lo vencio Shifty y el outbox
# vence el link en MP), ni los acreditados ni ``refunded``.
LIVE_CHARGE_PAYMENT_STATUSES: frozenset[str] = frozenset(
    {PaymentStatus.PENDING.value, PaymentStatus.REJECTED.value}
)


# Unica fuente de verdad del grafo de la region de facturacion.
#
# Invariante central: una vez que la plata se asento (approved /
# manual_confirmed) o se devolvio (refunded), no puede degradarse en silencio
# a un estado sin acreditar. `refunded` es terminal: antes el ratchet dejaba
# pasar refunded -> approved porque solo bloqueaba las degradaciones, y un
# webhook tardio podia revivir un pago ya devuelto.
#
# Los caminos de recuperacion si se mantienen: un cobro rechazado o vencido
# puede terminar acreditado (reintento del cliente, o conciliacion que
# encuentra en Mercado Pago un pago que nunca notifico).
ALLOWED_PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "rejected", "expired", "manual_confirmed"},
    "rejected": {"approved", "manual_confirmed", "expired"},
    "expired": {"approved", "manual_confirmed"},
    "approved": {"refunded"},
    "manual_confirmed": {"refunded"},
    "refunded": set(),
}


# Evento del outbox: "vencer este link de pago en Mercado Pago". Lo publica
# quien suelta o reemplaza un link en la misma transaccion y lo consume
# process_outbox_batch fuera de todo lock (B1-04). Vive aca (y
# ``payments.service`` lo reexporta) para que ``payments.links`` lo use sin
# importar el service.
EVENT_PREFERENCE_EXPIRE = "payment.preference.expire"

# Separador de la ``external_reference`` de un link: ``<turno>:<link_ref>``.
# Los ids de turno son ULID (sin ``:``), asi que el turno es lo de antes.
EXTERNAL_REFERENCE_SEPARATOR = ":"


def external_reference_for(appointment_id: str, link_ref: str | None) -> str:
    """``external_reference`` de un link de pago (revision de perf/f4-pay).

    Cada link lleva un nonce propio (``Payment.link_ref``): el pago de MP no
    trae ``preference_id``, asi que es la senal que controla Shifty para
    saber de QUE link es un pago. Sin nonce (links creados antes del deploy)
    es el id del turno, como siempre: esos links siguen matcheando.
    """
    if not link_ref:
        return appointment_id
    return f"{appointment_id}{EXTERNAL_REFERENCE_SEPARATOR}{link_ref}"


def appointment_id_from_reference(reference: str) -> str:
    """El turno de una ``external_reference``, con o sin nonce de link."""
    return reference.split(EXTERNAL_REFERENCE_SEPARATOR, 1)[0]


def is_placeholder_preference_id(preference_id: str | None) -> bool:
    """Un link placeholder (``pref_<turno>``): no existe en Mercado Pago."""
    return not preference_id or preference_id.startswith("pref_")


def can_apply_payment_status(current: str, attempted: str) -> bool:
    """Indica si el pago puede pasar de ``current`` a ``attempted``."""
    if attempted == current:
        return True
    return attempted in ALLOWED_PAYMENT_TRANSITIONS.get(current, set())


class PaymentGatewayConfig(BaseEntity):
    __tablename__ = "payment_gateway_configs"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="mercadopago")
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_mode: Mapped[str] = mapped_column(String(20), default="manual")
    oauth_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "store_id", "provider", name="uq_gateway_config_store_provider"
        ),
    )


class Payment(BaseEntity):
    __tablename__ = "payments"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="mercadopago")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    discount_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="ARS")
    # Columna privada: la unica escritura legitima es apply_status(). Se expone
    # como hybrid_property de solo lectura, asi que `payment.status = "approved"`
    # levanta AttributeError en vez de saltearse el grafo (mismo patron que
    # Appointment; 2026-09-17, B2-08). A nivel clase sigue sirviendo para
    # filtrar en queries.
    _status: Mapped[str] = mapped_column(
        "status", String(50), default=PaymentStatus.PENDING.value, index=True
    )
    promotion_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preference_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    payment_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nonce del link VIGENTE: va en su ``external_reference`` y la integridad
    # del webhook lo exige (revision de perf/f4-pay, 2026-09-25). NULL = link
    # creado antes de la columna (referencia = id del turno).
    link_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    transaction_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON, nullable=True
    )
    # Snapshot de la regla de sena aplicada (monto base, recargo y motivos):
    # explica el monto aunque la tienda cambie la configuracion despues.
    deposit_rule: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON, nullable=True
    )
    # Optimistic locking, igual que en Appointment.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        UniqueConstraint(
            "store_id", "appointment_id", name="uq_payments_store_appointment"
        ),
    )

    def __init__(self, **kwargs: Any) -> None:
        # `status=` es el nombre publico que usan el service y los tests al crear.
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
    def is_accredited(self) -> bool:
        """La plata efectivamente entro (aprobada o confirmada manual)."""
        return self.status in ACCREDITED_PAYMENT_STATUSES

    @property
    def current_external_reference(self) -> str:
        """La ``external_reference`` del link vigente de este cobro."""
        return external_reference_for(self.appointment_id, self.link_ref)

    @property
    def is_live_charge(self) -> bool:
        """El cobro sigue abierto: su link se puede pagar (D1, 2026-09-25)."""
        return self.status in LIVE_CHARGE_PAYMENT_STATUSES

    def reopen_for_panel_link(self) -> bool:
        """``expired -> pending`` para un link NUEVO generado desde el panel.

        Revision de perf/f4-pay (2026-09-25, opcion b del coordinador): la
        arista NO esta en ``ALLOWED_PAYMENT_TRANSITIONS`` a proposito. Ese
        grafo lo usa el webhook, y un ``in_process`` tardio de la preferencia
        vieja reabriria un cobro vencido (quizas de un turno ya cancelado).
        Unico llamador: ``payments.service.create_panel_payment_preference``,
        con el turno lockeado y no soltado, despues de sellar un
        ``preference_id`` nuevo (un webhook de la preferencia vieja ya no
        pasa la integridad). Lo fija ``tests/unit/test_reabrir_cobro_para_link_del_panel.py``.

        Devuelve False (sin tocar nada) si el cobro no esta ``expired`` o si
        no tiene un link real que cobrar.
        """
        if self.status != PaymentStatus.EXPIRED.value:
            return False
        if is_placeholder_preference_id(self.preference_id):
            return False
        self._status = PaymentStatus.PENDING.value
        return True

    def apply_status(
        self, new_status: str, *, payload: dict[str, JsonValue] | None = None
    ) -> bool:
        """Aplica una transicion de estado validada por el grafo del pago.

        La entidad es la unica que muta su propio estado (Tell-Don't-Ask): antes
        el estado se asignaba a mano desde el service y cualquier lugar podia
        escribir ``payment.status = 'approved'`` salteando el grafo. Devuelve
        False si la transicion es ilegal (se ignora, para tolerar la reentrega
        de webhooks) y sella ``paid_at`` al acreditar.
        """
        if not can_apply_payment_status(self.status, new_status):
            return False
        self._status = new_status
        self.raw_payload = payload or self.raw_payload
        if self.status in {
            PaymentStatus.APPROVED.value,
            PaymentStatus.MANUAL_CONFIRMED.value,
        }:
            self.paid_at = self.paid_at or datetime.now(timezone.utc)
        return True


class PaymentLinkHistory(BaseEntity):
    """Un link de pago que el cobro dejo de usar (revision de perf/f4-pay).

    El webhook de un pago del link retirado puede llegar tarde o
    reentregarse, y el link sigue pagable hasta que MP lo vence (con
    ``binary_mode`` no hay cupones de efectivo pendientes): ese pago tiene que
    poder reconocerse (misma referencia, mismo importe de ESE link) y
    aplicarse o alertarse, no perderse. Lo escribe ``payments.links``.
    """

    __tablename__ = "payment_link_history"
    __table_args__ = (
        Index("ix_payment_link_history_payment_retired", "payment_id", "retired_at"),
    )

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"))
    # NULL = link de antes del nonce: su referencia es el id del turno.
    link_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    preference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10))
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebhookInbox(BaseEntity):
    __tablename__ = "webhook_inbox"
    # Historico que lee la purga de retencion (F1-19, migracion e5f7a9b1c3d6).
    __table_args__ = (
        Index(
            "ix_webhook_inbox_processed_history",
            "processed_at",
            postgresql_where=text("processed_at IS NOT NULL"),
            sqlite_where=text("processed_at IS NOT NULL"),
        ),
    )

    store_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), default="mercadopago")
    event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def mark_processed(self) -> None:
        self.processed_at = datetime.now(timezone.utc)
        self.error = None

    def register_failure(self, reason: str) -> None:
        """Cuenta un intento fallido y abandona el evento al agotar los reintentos.

        No marcamos ``processed_at`` mientras queden intentos: el worker del inbox
        vuelve a tomar la fila y reintenta. Al agotarlos la damos por vencida para
        que deje de reprocesarse y quede visible en ``failed_webhooks``.
        """
        self.attempts = (self.attempts or 0) + 1
        self.error = reason[:1000]
        if self.attempts >= WEBHOOK_INBOX_MAX_ATTEMPTS:
            self.processed_at = datetime.now(timezone.utc)


class OutboxMessage(BaseEntity):
    __tablename__ = "outbox_messages"
    # Retome de reclamos de ``payment.preference.expire`` con lease vencido
    # (``payments/jobs.py::_claim_and_expire_preferences``, cada minuto): sin
    # el parcial caia en ``ix_outbox_messages_event_type`` y recorria todo el
    # historico del evento (F1-14, migracion a6c8e0f2b4d7). El predicado es el
    # literal de ``PREFERENCE_EXPIRE_CLAIM``.
    __table_args__ = (
        Index(
            "ix_outbox_expire_claims",
            "processed_at",
            postgresql_where=text("error = 'claimed:payment.preference.expire'"),
            sqlite_where=text("error = 'claimed:payment.preference.expire'"),
        ),
        # Historico que lee la purga de retencion (F1-19, migracion e5f7a9b1c3d6).
        Index(
            "ix_outbox_processed_history",
            "processed_at",
            postgresql_where=text("processed_at IS NOT NULL"),
            sqlite_where=text("processed_at IS NOT NULL"),
        ),
    )

    store_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Mismo contador y mismo techo que WebhookInbox (regla 7): el intento es
    # del mensaje, no del lote. Sin esto un mensaje que siempre falla se
    # reintentaba cada minuto para siempre (2026-09-17, B2-12).
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def register_failure(self, reason: str) -> None:
        """Cuenta un intento fallido y abandona el mensaje al agotar los reintentos.

        Mientras queden intentos ``processed_at`` sigue en NULL y el beat lo
        vuelve a tomar. Al agotarlos se da por procesado (con ``error``
        anotado) para que deje de ocupar lugar en cada lote.
        """
        self.attempts = (self.attempts or 0) + 1
        self.error = reason[:1000]
        if self.attempts >= WEBHOOK_INBOX_MAX_ATTEMPTS:
            self.processed_at = datetime.now(timezone.utc)


__all__ = [
    "ALLOWED_PAYMENT_TRANSITIONS",
    "EVENT_PREFERENCE_EXPIRE",
    "PaymentLinkHistory",
    "LIVE_CHARGE_PAYMENT_STATUSES",
    "WEBHOOK_INBOX_MAX_ATTEMPTS",
    "can_apply_payment_status",
    "is_placeholder_preference_id",
    "external_reference_for",
    "appointment_id_from_reference",
    "JsonPrimitive",
    "JsonValue",
    "OutboxMessage",
    "Payment",
    "PaymentGatewayConfig",
    "PaymentStatus",
    "WebhookInbox",
]
