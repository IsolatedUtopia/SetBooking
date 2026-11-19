from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.seat import Seat


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("start_slot < end_slot", name="ck_reservations_slot_order"),
        CheckConstraint(
            "status IN ('PENDING','CHECKED_IN','COMPLETED','CANCELLED','NO_SHOW')",
            name="ck_reservations_status",
        ),
        Index("ix_reservations_user_date", "user_id", "date"),
        Index("ix_reservations_seat_date", "seat_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id", ondelete="RESTRICT"), index=True)
    date: Mapped[date] = mapped_column(Date)
    start_slot: Mapped[int] = mapped_column(Integer)
    end_slot: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default=ReservationStatus.PENDING, server_default=text("'PENDING'")
    )
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    seat: Mapped["Seat"] = relationship(lazy="selectin")
    
    slots: Mapped[list["ReservationSlot"]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan", lazy="selectin"
    )


class ReservationSlot(Base):
    __tablename__ = "reservation_slots"
    __table_args__ = (
        UniqueConstraint("seat_id", "date", "slot_index", name="uq_reservation_slots_seat_slot"),
        CheckConstraint("slot_index >= 0", name="ck_reservation_slots_slot_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), index=True
    )
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id", ondelete="RESTRICT"))
    date: Mapped[date] = mapped_column(Date)
    slot_index: Mapped[int] = mapped_column(Integer)

    reservation: Mapped["Reservation"] = relationship(back_populates="slots")