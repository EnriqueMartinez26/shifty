from typing import Optional
from sqlalchemy import String, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.models.base import Base

class StaffServiceModel(Base):
    __tablename__ = "staff_services"

    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True)
    service_id: Mapped[str] = mapped_column(String, ForeignKey("services.id", ondelete="CASCADE"), primary_key=True)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(2, 1))
