"""预约业务：创建预约。

设计要点：
1. 一张预约单 = reservations 一行 + reservation_slots 每格一行。
2. 防超卖不靠"先查再插"，靠 uq_reservation_slots_seat_slot 唯一索引，
   撞车时把 IntegrityError 翻译成 409。
3. 单据与格子在同一事务里提交：要么都成功，要么都回滚。
"""

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Reservation, ReservationSlot, ReservationStatus, Seat, User
from app.schemas.reservation import ReservationCreate

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# 签到
# ---------------------------------------------------------------------------


def _local_now() -> datetime:
    """业务时间用本地时区：日历上的 08:00 是本地 08:00，不是 UTC 08:00。"""
    return datetime.now()


def _slot_start(day: date, slot_index: int) -> datetime:
    """某天第 slot_index 个时段开始的那一刻（本地时间）。"""
    minutes = settings.day_start_hour * 60 + slot_index * settings.slot_minutes
    return datetime.combine(day, time.min) + timedelta(minutes=minutes)


def check_in_window(day: date, start_slot: int, now: datetime | None = None) -> str | None:
    """签到窗口：[开始 - 15 分钟, 开始 + 30 分钟]。

    返回 None 表示可以签到；返回字符串表示拒绝原因。
    写成纯函数（不查库、不读当前时间）是为了能直接单测。
    """
    moment = now or _local_now()
    start = _slot_start(day, start_slot)
    earliest = start - timedelta(minutes=settings.check_in_lead_minutes)
    latest = start + timedelta(minutes=settings.no_show_release_minutes)

    if moment < earliest:
        return f"还没到签到时间，{earliest:%H:%M} 起可签到"
    if moment > latest:
        return f"签到已截止，{latest:%H:%M} 后视为爽约"
    return None


async def check_in_reservation(
    session: AsyncSession, user: User, reservation_id: int
) -> Reservation:
    """签到：PENDING → CHECKED_IN，写 checked_in_at。"""
    reservation = await session.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")

    # 状态守卫：先判"能不能",再判"时间对不对"
    if reservation.status == ReservationStatus.CHECKED_IN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该预约已签到，请勿重复操作"
        )
    if reservation.status != ReservationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该预约已取消或已结束，无法签到"
        )

    reason = check_in_window(reservation.date, reservation.start_slot)
    if reason is not None:
        raise _bad_request(reason)

    reservation.status = ReservationStatus.CHECKED_IN
    reservation.checked_in_at = _now_naive()  # 存 UTC，和 created_at 保持一致
    await session.commit()
    await session.refresh(reservation)
    return reservation

# ---------------------------------------------------------------------------
# 超时未签到 → 爽约 → 释放座位
# ---------------------------------------------------------------------------

# 只回看最近几天：扫描任务跑得再勤，也不该扫全表
NO_SHOW_LOOKBACK_DAYS = 7


def is_no_show(day: date, start_slot: int, now: datetime | None = None) -> bool:
    """过了「开始时间 + 30 分钟」还没签到，就算爽约。

    和签到窗口共用同一把尺子：窗口上界 = 爽约判定线。
    """
    moment = now or _local_now()
    deadline = _slot_start(day, start_slot) + timedelta(
        minutes=settings.no_show_release_minutes
    )
    return moment > deadline


async def release_no_shows(session: AsyncSession, now: datetime | None = None) -> list[int]:
    """扫描并释放超时未签到的预约，返回本次处理的预约 id 列表。

    幂等：用「守卫式 UPDATE」而不是「读出来改对象」——
    UPDATE ... WHERE id=? AND status='PENDING' 的 rowcount 决定这一次到底有没有改到。第二次运行的话一定都是0。
    """
    moment = now or _local_now()
    today = moment.date()

    stmt = select(Reservation).where(
        Reservation.status == ReservationStatus.PENDING,
        Reservation.date >= today - timedelta(days=NO_SHOW_LOOKBACK_DAYS),
        Reservation.date <= today,
    )
    candidates = (await session.scalars(stmt)).all()

    released: list[int] = []
    backlog_dates: list[date] = []      # 本次补扫到的「非今天」的单子

    for reservation in candidates:
        if not is_no_show(reservation.date, reservation.start_slot, moment):
            continue

        result = await session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation.id,
                Reservation.status == ReservationStatus.PENDING,
            )
            .values(status=ReservationStatus.NO_SHOW)
        )
        if result.rowcount == 0:
            continue

        reservation.slots.clear()
        released.append(reservation.id)

        if reservation.date < today:
            backlog_dates.append(reservation.date)

    await session.commit()

    # --- 可观测性：让「漏跑」自己说话 ---
    if released:
        logger.info("超时释放 %d 条，ids=%s", len(released), released)
    if backlog_dates:
        logger.warning(
            "补扫到 %d 条非今天的过期预约（最早 %s）：调度器可能停摆过，请检查是否漏跑",
            len(backlog_dates),
            min(backlog_dates),
        )

    return released
