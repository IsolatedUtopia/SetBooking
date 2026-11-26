from datetime import date, datetime, time, timedelta

from app.models.seat import Seat

TOMORROW = date.today() + timedelta(days=1)
START = datetime.combine(TOMORROW, time(8, 0))


def payload(**overrides):
    data = {
        "seat_id": 1,
        "date": TOMORROW.isoformat(),
        "start_slot": 0,
        "end_slot": 2,
    }
    data.update(overrides)
    return data


async def retire(session_factory, seat_id: int = 1) -> None:
    """直接改库：后台停用座位走的就是这一列。"""
    async with session_factory() as session:
        seat = await session.get(Seat, seat_id)
        assert seat is not None
        seat.is_active = False
        await session.commit()


async def test_retired_seat_keeps_existing_reservation_on_calendar(
    client, session_factory, headers
) -> None:
    assert (await client.post("/api/v1/reservations", json=payload(), headers=headers)).status_code == 201
    await retire(session_factory)

    resp = await client.get(f"/api/v1/areas/1/calendar?date={TOMORROW.isoformat()}", headers=headers)
    assert resp.status_code == 200
    seat = next(s for s in resp.json()["seats"] if s["seat_id"] == 1)
    assert seat["is_active"] is False
    assert seat["occupied_slots"] == [0, 1]


async def test_check_in_still_works_after_seat_retired(
    client, session_factory, headers, monkeypatch
) -> None:
    resp = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    reservation_id = resp.json()["id"]
    await retire(session_factory)

    monkeypatch.setattr("app.services.reservation._local_now", lambda: START - timedelta(minutes=5))
    resp = await client.post(f"/api/v1/reservations/{reservation_id}/check-in", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CHECKED_IN"


async def test_retired_seat_cannot_be_booked_again(
    client, session_factory, headers
) -> None:
    await retire(session_factory)

    resp = await client.post("/api/v1/reservations", json=payload(), headers=headers)
    assert resp.status_code == 404