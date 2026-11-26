from collections import defaultdict
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.area import Area
from app.models.reservation import ReservationSlot
from app.models.seat import Seat
from app.schemas.calendar import AreaDayCalendar, SeatDay, SlotLabel

SLOT_COUNT = (settings.day_end_hour - settings.day_start_hour) * 60 // settings.slot_minutes


def slot_label(slot_index: int) -> str:
    start_minutes = settings.day_start_hour * 60 + slot_index * settings.slot_minutes
    end_minutes = start_minutes + settings.slot_minutes
    start_h, start_m = divmod(start_minutes, 60)
    end_h, end_m = divmod(end_minutes, 60)
    return f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"


def check_date_window(day: date) -> None:
    today = date.today()
    if day < today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能查看过去的日期",
        )
    latest = today + timedelta(days=settings.booking_window_days)
    if day > latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"只能查看未来 {settings.booking_window_days} 天内的日期",
        )


async def get_area_calendar(session: AsyncSession, area_id: int, day: date) -> AreaDayCalendar:
    area = await session.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="区域不存在")

    check_date_window(day)

    seats = list(
        await session.scalars(
            select(Seat).where(Seat.area_id == area_id).order_by(Seat.code)
        )
    )

    occupied: dict[int, list[int]] = defaultdict(list)
    if seats:
        rows = await session.execute(
            select(ReservationSlot.seat_id, ReservationSlot.slot_index)
            .where(
                ReservationSlot.date == day,
                ReservationSlot.seat_id.in_([seat.id for seat in seats]),
            )
            .order_by(ReservationSlot.seat_id, ReservationSlot.slot_index)
        )
        for seat_id, slot_index in rows.all():
            occupied[seat_id].append(slot_index)

    return AreaDayCalendar(
        area_id=area_id,
        date=day,
        slot_count=SLOT_COUNT,
        slots=[SlotLabel(slot_index=i, label=slot_label(i)) for i in range(SLOT_COUNT)],
        seats=[
            SeatDay(
                seat_id=seat.id,
                code=seat.code,
                has_power=seat.has_power,
                is_active=seat.is_active,
                occupied_slots=occupied.get(seat.id, []),
            )
            for seat in seats
            if seat.is_active or occupied.get(seat.id)
        ],
    )