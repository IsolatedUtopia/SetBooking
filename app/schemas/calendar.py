from datetime import date

from pydantic import BaseModel

#制定日历响应格式

class SlotLabel(BaseModel):
    slot_index: int
    label: str


class SeatDay(BaseModel):
    seat_id: int
    code: str
    has_power: bool
    occupied_slots: list[int]


class AreaDayCalendar(BaseModel):
    area_id: int
    date: date
    slot_count: int
    slots: list[SlotLabel]
    seats: list[SeatDay]