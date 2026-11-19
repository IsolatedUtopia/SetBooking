from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SeatBrief(BaseModel):
    """预约里带的座位信息，只要 id 和编号，不要座位表的其他字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str


class ReservationCreate(BaseModel):
    seat_id: int
    date: date
    start_slot: int = Field(ge=0, description="起始时段序号（含）")
    end_slot: int = Field(ge=0, description="结束时段序号（不含）")

    @model_validator(mode="after")
    def check_slot_range(self) -> "ReservationCreate":
        if self.end_slot <= self.start_slot:
            raise ValueError("结束时段必须大于起始时段")
        count = self.end_slot - self.start_slot
        if count > settings.max_slots_per_reservation:
            raise ValueError(f"一次最多预约 {settings.max_slots_per_reservation} 个时段")
        return self


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seat_id: int
    seat: SeatBrief
    date: date
    start_slot: int
    end_slot: int
    status: ReservationStatus
    checked_in_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
