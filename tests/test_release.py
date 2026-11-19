from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from app.models import ReservationSlot
from app.services.reservation import is_no_show, release_no_shows
from tests.helpers import register_and_login

TOMORROW = date.today() + timedelta(days=1)
START = datetime.combine(TOMORROW, time(8, 0))


def payload(**overrides: object) -> dict:
    data: dict = {"seat_id": 1, "date": TOMORROW.isoformat(), "start_slot": 0, "end_slot": 2}
    data.update(overrides)
    return data


def test_is_no_show_boundary() -> None:
    """判定线：开始 + 30 分钟；正好到点仍算签到有效，过 1 秒才爽约。"""
    assert is_no_show(TOMORROW, 0, START + timedelta(minutes=29)) is False
    assert is_no_show(TOMORROW, 0, START + timedelta(minutes=30)) is False
    assert is_no_show(TOMORROW, 0, START + timedelta(minutes=30, seconds=1)) is True


async def test_release_marks_no_show_and_frees_seat(client, session_factory) -> None:
    """释放 → 状态变 NO_SHOW、格子被删、别人能约同一个时段。"""
    headers = await register_and_login(client)
    created = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    assert created.status_code == 201
    reservation_id = created.json()["id"]

    async with session_factory() as session:
        released = await release_no_shows(session, now=START + timedelta(minutes=31))
    assert released == [reservation_id]

    mine = await client.get("/api/v1/reservations/me", headers=headers)
    assert mine.json()[0]["status"] == "NO_SHOW"

    calendar = await client.get(f"/api/v1/areas/1/calendar?date={TOMORROW.isoformat()}")
    assert calendar.json()["seats"][0]["occupied_slots"] == []

    other = await register_and_login(client, email="other@example.com", student_no="20220002")
    again = await client.post("/api/v1/reservations", json=payload(), headers=other)
    assert again.status_code == 201


async def test_release_is_idempotent(client, session_factory) -> None:
    """同一批数据连跑两次：第二次什么都不该处理，格子也不该多删。"""
    headers = await register_and_login(client)
    created = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    reservation_id = created.json()["id"]

    async with session_factory() as session:
        first = await release_no_shows(session, now=START + timedelta(minutes=31))
    async with session_factory() as session:
        second = await release_no_shows(session, now=START + timedelta(minutes=31))

    assert first == [reservation_id]
    assert second == []

    async with session_factory() as session:
        slot_count = await session.scalar(select(func.count()).select_from(ReservationSlot))
    assert slot_count == 0


async def test_release_ignores_cancelled_and_future(client, session_factory) -> None:
    """已取消的不动；还没到期的也不动。"""
    headers = await register_and_login(client)

    cancelled = await client.post("/api/v1/reservations", json=payload(seat_id=1), headers=headers)
    cancelled_id = cancelled.json()["id"]
    await client.delete(f"/api/v1/reservations/{cancelled_id}", headers=headers)

    future = await client.post(
        "/api/v1/reservations",
        json=payload(seat_id=2, start_slot=24, end_slot=26),  # 20:00 才开始
        headers=headers,
    )
    assert future.status_code == 201
    future_id = future.json()["id"]

    async with session_factory() as session:
        released = await release_no_shows(session, now=START + timedelta(minutes=31))
    assert released == []

    mine = await client.get("/api/v1/reservations/me", headers=headers)
    statuses = {item["id"]: item["status"] for item in mine.json()}
    assert statuses[cancelled_id] == "CANCELLED"
    assert statuses[future_id] == "PENDING"
