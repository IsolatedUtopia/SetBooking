from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.models.reservation import Reservation
from app.schemas.reservation import ReservationCreate, ReservationRead
from app.services.reservation import create_reservation

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
async def create_reservation_endpoint(
    data: ReservationCreate, session: SessionDep, current_user: CurrentUser
) -> Reservation:
    return await create_reservation(session, current_user, data)
