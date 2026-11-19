from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.models import User
from app.services.reservation import _now_naive, release_no_shows, should_ban
from tests.helpers import register_and_login

TOMORROW = date.today() + timedelta(days=1)
START = datetime.combine(TOMORROW, time(8, 0))


def payload(**overrides: object) -> dict:
    data: dict = {"seat_id": 1, "date": TOMORROW.isoformat(), "start_slot": 0, "end_slot": 2}
    data.update(overrides)
    return data


async def test_should_ban_threshold() -> None:
    """阈值来自配置：默认 3 次。"""
    assert should_ban(2) is False
    assert should_ban(3) is True
    assert should_ban(10) is True


async def test_release_increments_no_show_count(client, session_factory) -> None:
    headers = await register_and_login(client)
    created = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    assert created.status_code == 201

    async with session_factory() as session:
        await release_no_shows(session, now=START + timedelta(minutes=31))

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        assert user.no_show_count == 1
        assert user.banned_until is None


async def test_third_no_show_bans_and_blocks_booking(client, session_factory) -> None:
    headers = await register_and_login(client)

    # 先把他打到「已经爽约 2 次」
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        user.no_show_count = 2
        await session.commit()

    created = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    assert created.status_code == 201

    async with session_factory() as session:
        await release_no_shows(session, now=START + timedelta(minutes=31))

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        assert user.no_show_count == 0            # 封禁时清零，开始新一轮
        assert user.banned_until is not None
        assert user.banned_until > _now_naive()

    blocked = await client.post("/api/v1/reservations", json=payload(seat_id=2), headers=headers)
    assert blocked.status_code == 403
    assert "封禁" in blocked.json()["detail"]


async def test_expired_ban_allows_booking(client, session_factory) -> None:
    """解封不需要定时任务：banned_until 一过期，判断自然放行。"""
    headers = await register_and_login(client)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        user.banned_until = _now_naive() - timedelta(days=1)
        await session.commit()

    ok = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    assert ok.status_code == 201
