from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Numeric, ForeignKey
from core.models import BaseEntity
import ulid

class Service(BaseEntity):
    __tablename__ = "services"
    
    public_id: Mapped[str] = mapped_column(
        String(26), 
        unique=True, 
        default=lambda: str(ulid.ULID()), 
        index=True
    )
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    color: Mapped[str | None] = mapped_column(String(20)) # Para visualización en calendario
    youtube_trailer_url: Mapped[str | None] = mapped_column(String(500))
