"""预约业务：创建预约。

设计要点：
1. 一张预约单 = reservations 一行 + reservation_slots 每格一行。
2. 防超卖不靠"先查再插"，靠 uq_reservation_slots_seat_slot 唯一索引，
   撞车时把 IntegrityError 翻译成 409。
3. 单据与格子在同一事务里提交：要么都成功，要么都回滚。
"""

from datetime import UTC, date, datetime
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Reservation, ReservationSlot, ReservationStatus, Seat, User
from app.schemas.reservation import ReservationCreate

SLOT_COUNT = (settings.day_end_hour - settings.day_start_hour) * 60 // settings.slot_minutes

OCCUPYING_STATUSES = [
    s.value for s in (ReservationStatus.PENDING, ReservationStatus.CHECKED_IN)
]


def _now_naive() -> datetime:
    """库里 DateTime 不带时区，统一按 UTC 存，比较前摘掉 tzinfo。"""
    return datetime.now(UTC).replace(tzinfo=None)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _check_user_allowed(user: User) -> None:
    if user.banned_until is not None and user.banned_until > _now_naive():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号因多次爽约被封禁，解封时间 {user.banned_until:%Y-%m-%d %H:%M}",
        )


def _check_date_window(day: date) -> None:
    today = date.today()
    if day < today:
        raise _bad_request("不能预约过去的日期")
    if (day - today).days > settings.booking_window_days:
        raise _bad_request(f"最多只能预约未来 {settings.booking_window_days} 天内的座位")


def _check_slot_range(start_slot: int, end_slot: int) -> None:
    if start_slot < 0 or end_slot > SLOT_COUNT:
        raise _bad_request(f"时段范围必须在 0 到 {SLOT_COUNT} 之间")


def _check_not_started(day: date, start_slot: int) -> None:
    if day != date.today():
        return
    now = datetime.now()
    minutes_from_open = now.hour * 60 + now.minute - settings.day_start_hour * 60
    current_slot = minutes_from_open // settings.slot_minutes
    if start_slot < current_slot:
        raise _bad_request("该时段已经开始，不能预约")


async def _get_active_seat(session: AsyncSession, seat_id: int) -> Seat:
    seat = await session.get(Seat, seat_id)
    if seat is None or not seat.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="座位不存在或已停用")
    return seat


async def _count_user_day_reservations(session: AsyncSession, user_id: int, day: date) -> int:
    stmt = (
        select(func.count())
        .select_from(Reservation)
        .where(
            Reservation.user_id == user_id,
            Reservation.date == day,
            Reservation.status.in_(OCCUPYING_STATUSES),
        )
    )
    return int((await session.scalar(stmt)) or 0)


async def _count_user_overlapping_slots(
    session: AsyncSession, user_id: int, day: date, start_slot: int, end_slot: int
) -> int:
    stmt = (
        select(func.count())
        .select_from(ReservationSlot)
        .join(Reservation, Reservation.id == ReservationSlot.reservation_id)
        .where(
            Reservation.user_id == user_id,
            ReservationSlot.date == day,
            ReservationSlot.slot_index >= start_slot,
            ReservationSlot.slot_index < end_slot,
            Reservation.status.in_(OCCUPYING_STATUSES),
        )
    )
    return int((await session.scalar(stmt)) or 0)


async def create_reservation(
    session: AsyncSession, user: User, data: ReservationCreate
) -> Reservation:
    # 第一组：不用查库就能判断的（便宜的先做，省一次往返）
    _check_user_allowed(user)
    _check_date_window(data.date)
    _check_slot_range(data.start_slot, data.end_slot)
    _check_not_started(data.date, data.start_slot)

    # 第二组：需要查库的
    seat = await _get_active_seat(session, data.seat_id)

    used = await _count_user_day_reservations(session, user.id, data.date)
    if used >= settings.max_reservations_per_day:
        raise _bad_request(f"每人每天最多预约 {settings.max_reservations_per_day} 次")

    if await _count_user_overlapping_slots(
        session, user.id, data.date, data.start_slot, data.end_slot
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="你在该时段已有预约，请勿重复提交",
        )

    # 第三组：写。这条路径上没有任何"先查后插"的判断来决定能不能成功，
    # 能不能成功最终由数据库的唯一索引裁决。
    reservation = Reservation(
        user_id=user.id,
        seat_id=seat.id,
        date=data.date,
        start_slot=data.start_slot,
        end_slot=data.end_slot,
        status=ReservationStatus.PENDING,
    )
    reservation.slots = [
        ReservationSlot(seat_id=seat.id, date=data.date, slot_index=i)
        for i in range(data.start_slot, data.end_slot)
    ]
    session.add(reservation)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该座位在所选时段已被预约",
        ) from None

    await session.refresh(reservation)
    return reservation

async def list_my_reservations(
    session: AsyncSession, user_id: int, limit: int = 50
) -> Sequence[Reservation]:
    """我的预约：新的在前，同一天按开始时段排。"""
    stmt = (
        select(Reservation)
        .where(Reservation.user_id == user_id)
        .order_by(Reservation.date.desc(), Reservation.start_slot.asc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def cancel_reservation(
    session: AsyncSession, user: User, reservation_id: int
) -> None:
    """取消预约：改状态 + 删掉占用格子（删格子才是真正把座位还回去）。"""
    reservation = await session.get(Reservation, reservation_id)

    # 不属于自己的预约统一回 404，而不是 403：
    # 403 等于告诉别人"这个 id 存在，只是不是你的"，会被用来枚举预约号。
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")

    if reservation.status == ReservationStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该预约已取消，请勿重复操作"
        )
    if reservation.status in (ReservationStatus.COMPLETED, ReservationStatus.NO_SHOW):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该预约已结束，无法取消"
        )

    reservation.status = ReservationStatus.CANCELLED
    reservation.cancelled_at = _now_naive()

    # cascade="all, delete-orphan"：清空子集合 = flush 时 DELETE 这些格子行。
    # 格子一删，唯一索引立刻放开，座位就回到"可预约"状态。
    reservation.slots.clear()

    await session.commit()

