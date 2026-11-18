import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  ← 必须！否则建表时只建被 import 过的模型
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models import Area, Seat


@pytest_asyncio.fixture
async def client():
    # 每个测试一个全新的内存库：进程结束就没了，永远不会污染 dev.db
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSession = async_sessionmaker(engine, expire_on_commit=False)

    # 基础数据：1 个区域 + 3 个座位（A-01、A-03 有电源）
    async with TestSession() as session:
        area = Area(name="A 区·测试", description="单元测试用区域")
        area.seats = [Seat(code=f"A-{i:02d}", has_power=(i % 2 == 1)) for i in range(1, 4)]
        session.add(area)
        await session.commit()

    async def override_get_session():
        async with TestSession() as session:
            yield session

    # 关键：把生产用的 get_session 换成测试库的
    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
