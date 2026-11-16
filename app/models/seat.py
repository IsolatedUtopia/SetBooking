from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint("area_id", "code", name="uq_seats_area_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(16))
    has_power: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    area: Mapped["Area"] = relationship(back_populates="seats")