from datetime import date, timedelta

from httpx import AsyncClient

from tests.helpers import register_and_login

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

URL = "/api/v1/reservations"


def payload(seat_id: int = 1, start: int = 0, end: int = 2, day: str = TOMORROW) -> dict:
    return {"seat_id": seat_id, "date": day, "start_slot": start, "end_slot": end}


async def test_create_reservation_success(client: AsyncClient):
    headers = await register_and_login(client)
    resp = await client.post(URL, json=payload(), headers=headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["seat"]["code"] == "A-01"
    assert body["start_slot"] == 0 and body["end_slot"] == 2


async def test_create_without_token_401(client: AsyncClient):
    resp = await client.post(URL, json=payload())
    assert resp.status_code == 401


async def test_same_user_duplicate_409(client: AsyncClient):
    headers = await register_and_login(client)
    await client.post(URL, json=payload(), headers=headers)

    resp = await client.post(URL, json=payload(), headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "你在该时段已有预约，请勿重复提交"


async def test_seat_taken_by_other_user_409(client: AsyncClient):
    """这一条走的是数据库唯一索引，不是预检查——防超卖的真正验收。"""
    first = await register_and_login(client, "a@example.com", "20220001")
    second = await register_and_login(client, "b@example.com", "20220002")

    assert (await client.post(URL, json=payload(), headers=first)).status_code == 201
    resp = await client.post(URL, json=payload(), headers=second)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "该座位在所选时段已被预约"


async def test_too_many_slots_422(client: AsyncClient):
    headers = await register_and_login(client)
    resp = await client.post(URL, json=payload(start=0, end=5), headers=headers)

    assert resp.status_code == 422


async def test_past_date_400(client: AsyncClient):
    headers = await register_and_login(client)
    resp = await client.post(URL, json=payload(day=YESTERDAY), headers=headers)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "不能预约过去的日期"


async def test_my_reservations_list(client: AsyncClient):
    headers = await register_and_login(client)
    await client.post(URL, json=payload(), headers=headers)
    await client.post(URL, json=payload(seat_id=2, start=4, end=6), headers=headers)

    resp = await client.get(f"{URL}/me", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {item["seat"]["code"] for item in body} == {"A-01", "A-02"}


async def test_cancel_releases_seat_and_can_rebook(client: AsyncClient):
    headers = await register_and_login(client)
    created = (await client.post(URL, json=payload(), headers=headers)).json()
    calendar_url = f"/api/v1/areas/1/calendar?date={TOMORROW}"

    before = (await client.get(calendar_url)).json()
    assert before["seats"][0]["occupied_slots"] == [0, 1]

    resp = await client.delete(f"{URL}/{created['id']}", headers=headers)
    assert resp.status_code == 204

    after = (await client.get(calendar_url)).json()
    assert after["seats"][0]["occupied_slots"] == []

    again = await client.post(URL, json=payload(), headers=headers)
    assert again.status_code == 201


async def test_cancel_twice_409(client: AsyncClient):
    headers = await register_and_login(client)
    created = (await client.post(URL, json=payload(), headers=headers)).json()

    assert (await client.delete(f"{URL}/{created['id']}", headers=headers)).status_code == 204
    resp = await client.delete(f"{URL}/{created['id']}", headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "该预约已取消，请勿重复操作"


async def test_cancel_missing_404(client: AsyncClient):
    headers = await register_and_login(client)
    resp = await client.delete(f"{URL}/999999", headers=headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "预约不存在"
