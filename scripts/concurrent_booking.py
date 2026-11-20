"""并发抢座压测：验证唯一索引是否真的挡住了超卖。

用法：
    python -m scripts.concurrent_booking --seat 1 --day-offset 2 --users 20

前提：uvicorn 正在运行，且 .env 指向 MySQL。
"""

import argparse
import asyncio
import time
from collections import Counter
from datetime import date, timedelta

import httpx

API = "http://127.0.0.1:8000/api/v1"
PASSWORD = "Passw0rd!"
START_SLOT = 0
END_SLOT = 2


async def register_and_login(client: httpx.AsyncClient, index: int) -> str:
    email = f"race{index}@example.com"
    student_no = f"2024{index:06d}"

    resp = await client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "student_no": student_no,
            "password": PASSWORD,
            "name": f"并发用户{index}",
        },
    )
    if resp.status_code not in (201, 409):  # 409 = 之前跑过，直接登录
        raise RuntimeError(f"注册失败 {resp.status_code}: {resp.text}")

    resp = await client.post(
        f"{API}/auth/login",
        data={"username": email, "password": PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def book(
    client: httpx.AsyncClient, token: str, seat_id: int, day: date
) -> httpx.Response:
    return await client.post(
        f"{API}/reservations",
        json={
            "seat_id": seat_id,
            "date": day.isoformat(),
            "start_slot": START_SLOT,
            "end_slot": END_SLOT,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seat", type=int, default=1)
    parser.add_argument("--day-offset", type=int, default=2)
    parser.add_argument("--users", type=int, default=20)
    args = parser.parse_args()

    day = date.today() + timedelta(days=args.day_offset)

    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"目标：座位 {args.seat}，日期 {day}，时段 {START_SLOT}–{END_SLOT}，"
              f"{args.users} 个用户")

        tokens = await asyncio.gather(
            *(register_and_login(client, i) for i in range(args.users))
        )
        print(f"已准备 {len(tokens)} 个登录用户")

        started = time.perf_counter()
        results = await asyncio.gather(
            *(book(client, token, args.seat, day) for token in tokens)
        )
        elapsed = time.perf_counter() - started

        codes = Counter(r.status_code for r in results)
        print(f"\n耗时 {elapsed * 1000:.0f} ms")
        print(f"状态码分布：{dict(sorted(codes.items()))}")

        successes = [r.json() for r in results if r.status_code == 201]
        print(f"成功 {len(successes)} 个")
        for body in successes:
            print(f"  reservation id={body['id']} status={body['status']}")

        failures = {r.status_code: r.json().get("detail") for r in results if r.status_code != 201}
        print(f"失败原因：{failures}")

        calendar = (
            await client.get(f"{API}/areas/1/calendar", params={"date": day.isoformat()})
        ).json()
        seat = next(s for s in calendar["seats"] if s["seat_id"] == args.seat)
        print(f"\n日历上座位 {seat['code']} 的占用格：{seat['occupied_slots']}")
        print(f"该座位当天被占的格子总数：{len(seat['occupied_slots'])}（期望 {END_SLOT - START_SLOT}）")


if __name__ == "__main__":
    asyncio.run(main())
