from datetime import date, datetime, time, timedelta

import pytest
from httpx import AsyncClient

from app.services.reservation import _slot_start, check_in_window
from tests.helpers import register_and_login

TOMORROW = date.today() + timedelta(days=1)
URL = "/api/v1/reservations"
START = datetime.combine(TOMORROW, time(8, 0))  # 明天第一个时段的开始时刻


def payload() -> dict:
    return {
        "seat_id": 1,
        "date": TOMORROW.isoformat(),
        "start_slot": 0,
        "end_slot": 2,
    }


# ---------------------------------------------------------------------------
# 一、纯函数：窗口逻辑（不碰数据库，毫秒级）
# ---------------------------------------------------------------------------


def test_slot_start_maps_index_to_clock():
    assert _slot_start(TOMORROW, 0) == START
    assert _slot_start(TOMORROW, 3) == START + timedelta(minutes=90)
    assert _slot_start(TOMORROW, 27) == START + timedelta(minutes=810)  # 21:30


def test_window_accepts_lead_time_and_boundaries():
    # 开始前 15 分钟那一刻：允许（闭区间）
    assert check_in_window(TOMORROW, 0, now=START - timedelta(minutes=15)) is None
    # 正点
    assert check_in_window(TOMORROW, 0, now=START) is None
    # 开始后 30 分钟那一刻：仍然允许
    assert check_in_window(TOMORROW, 0, now=START + timedelta(minutes=30)) is None


def test_window_rejects_too_early():
    reason = check_in_window(TOMORROW, 0, now=START - timedelta(minutes=16))
    assert reason is not None
    assert "还没到签到时间" in reason
    assert "07:45" in reason


def test_window_rejects_too_late():
    reason = check_in_window(TOMORROW, 0, now=START + timedelta(minutes=31))
    assert reason is not None
    assert "签到已截止" in reason
    assert "08:30" in reason


# ---------------------------------------------------------------------------
# 二、接口：完整链路
# ---------------------------------------------------------------------------


async def test_check_in_success(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    headers = await register_and_login(client)
    created = (await client.post(URL, json=payload(), headers=headers)).json()
    assert created["status"] == "PENDING"

    # 把"现在"拨到开始前 5 分钟，避免依赖真实时钟
    monkeypatch.setattr(
        "app.services.reservation._local_now",
        lambda: START - timedelta(minutes=5),
    )

    resp = await client.post(f"{URL}/{created['id']}/check-in", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CHECKED_IN"
    assert body["checked_in_at"] is not None


async def test_check_in_twice_409(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    headers = await register_and_login(client)
    created = (await client.post(URL, json=payload(), headers=headers)).json()

    monkeypatch.setattr(
        "app.services.reservation._local_now", lambda: START - timedelta(minutes=5)
    )
    first = await client.post(f"{URL}/{created['id']}/check-in", headers=headers)
    assert first.status_code == 200

    second = await client.post(f"{URL}/{created['id']}/check-in", headers=headers)

    assert second.status_code == 409
    assert second.json()["detail"] == "该预约已签到，请勿重复操作"


async def test_check_in_too_early_400(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    headers = await register_and_login(client)
    created = (await client.post(URL, json=payload(), headers=headers)).json()

    monkeypatch.setattr(
        "app.services.reservation._local_now", lambda: START - timedelta(hours=2)
    )
    resp = await client.post(f"{URL}/{created['id']}/check-in", headers=headers)

    assert resp.status_code == 400
    assert "还没到签到时间" in resp.json()["detail"]


async def test_check_in_cancelled_409(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    headers = await register_and_login(client)
    created = (await client.post(URL, json=payload(), headers=headers)).json()
    await client.delete(f"{URL}/{created['id']}", headers=headers)

    monkeypatch.setattr(
        "app.services.reservation._local_now", lambda: START - timedelta(minutes=5)
    )
    resp = await client.post(f"{URL}/{created['id']}/check-in", headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "该预约已取消或已结束，无法签到"


async def test_check_in_other_users_reservation_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    owner = await register_and_login(client, "a@example.com", "20220001")
    other = await register_and_login(client, "b@example.com", "20220002")
    created = (await client.post(URL, json=payload(), headers=owner)).json()

    monkeypatch.setattr(
        "app.services.reservation._local_now", lambda: START - timedelta(minutes=5)
    )
    resp = await client.post(f"{URL}/{created['id']}/check-in", headers=other)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "预约不存在"
