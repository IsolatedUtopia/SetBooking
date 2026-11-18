import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import SessionDep
from app.models.area import Area
from app.models.seat import Seat
from app.schemas.area import AreaRead, SeatRead
from app.schemas.calendar import AreaDayCalendar
from app.services.calendar import get_area_calendar

router = APIRouter(prefix="/areas", tags=["areas"])


@router.get("", response_model=list[AreaRead])
async def list_areas(session: SessionDep) -> list[Area]:
    areas = await session.scalars(select(Area).order_by(Area.id))
    return list(areas)


@router.get("/{area_id}/seats", response_model=list[SeatRead])
async def list_seats(area_id: int, session: SessionDep) -> list[Seat]:
    area = await session.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="区域不存在")

    seats = await session.scalars(
        select(Seat)
        .where(Seat.area_id == area_id, Seat.is_active.is_(True))
        .order_by(Seat.code)
    )
    return list(seats)


@router.get("/{area_id}/calendar", response_model=AreaDayCalendar)
async def area_calendar(
    area_id: int,
    session: SessionDep,
    day: dt.date = Query(alias="date", description="查询日期，格式 YYYY-MM-DD"),
) -> AreaDayCalendar:
    return await get_area_calendar(session, area_id, day)