from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class OtpVerification(BaseEntity):
    __tablename__ = "otp_verifications"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    phone: Mapped[str] = mapped_column(String(30), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    code_hash: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # SOLO se setea cuando el cliente demostro conocer el codigo. consumed_at
    # tambien se usa para invalidar codigos al emitir uno nuevo, asi que NO
    # sirve como prueba de verificacion: usarlo permitia "verificar" un
    # telefono pidiendo dos codigos seguidos, sin conocer ninguno.
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # A QUE direccion se despacho el codigo. Sin esta columna, `verified_at`
    # solo decia "alguien acerto un codigo de este telefono", y el que pedia el
    # codigo elegia el buzon: saber un telefono ajeno y poner el email propio
    # alcanzaba para autogestionar los turnos de esa persona. 2026-09-20.
    #
    # NULLABLE por las filas anteriores a esa fecha, y NULL es FAIL CLOSED: una
    # verificacion sin email no otorga NINGUN privilegio, porque no se puede
    # saber contra que direccion se probo la posesion.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    @property
    def is_expired(self) -> bool:
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None
