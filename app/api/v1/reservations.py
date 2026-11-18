from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.models.reservation import Reservation
from app.schemas.reservation import ReservationCreate, ReservationRead
from app.services.reservation import (
    cancel_reservation,
    create_reservation,
    list_my_reservations,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
async def create_reservation_endpoint(
    data: ReservationCreate, session: SessionDep, current_user: CurrentUser
) -> Reservation:
    return await create_reservation(session, current_user, data)


@router.get("/me", response_model=list[ReservationRead])
async def list_my_reservations_endpoint(
    session: SessionDep, current_user: CurrentUser
) -> list[Reservation]:
    return list(await list_my_reservations(session, current_user.id))


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation_endpoint(
    reservation_id: int, session: SessionDep, current_user: CurrentUser
) -> None:
    await cancel_reservation(session, current_user, reservation_id)
