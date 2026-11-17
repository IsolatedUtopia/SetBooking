from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep
from app.models.area import Area
from app.models.seat import Seat
from app.schemas.area import AreaRead, SeatRead

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