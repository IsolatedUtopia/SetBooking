import asyncio

from sqlalchemy import select

import app.models  # noqa: F401
from app.db.session import SessionLocal, engine
from app.models.area import Area
from app.models.seat import Seat

AREAS = [
    ("A 区·靠窗", "安静、靠窗、有插座", "A", 5),
    ("B 区·静音", "全程禁言，适合刷题", "B", 3),
    ("C 区·维修中", "设备检修，暂未排座位", "C", 0),
]


async def seed() -> None:
    async with SessionLocal() as session:
        total_new_seats = 0
        for name, description, prefix, seat_count in AREAS:
            area = await session.scalar(select(Area).where(Area.name == name))
            if area is None:
                area = Area(name=name, description=description)
                session.add(area)
                await session.flush()
                print(f"created area id={area.id} name={area.name}")

            existing = set(
                (await session.scalars(select(Seat.code).where(Seat.area_id == area.id))).all()
            )
            added = 0
            for i in range(1, seat_count + 1):
                code = f"{prefix}-{i:02d}"
                if code in existing:
                    continue
                session.add(Seat(area_id=area.id, code=code, has_power=(i % 2 == 1)))
                added += 1

            total_new_seats += added
            print(f"area={area.name} id={area.id}, new seats={added}")

        await session.commit()
        print(f"done, total new seats={total_new_seats}")


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())