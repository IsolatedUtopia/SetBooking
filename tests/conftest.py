import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  ← 必须！否则建表时只建被 import 过的模型
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models import Area, Seat
from tests.helpers import register_and_login


@pytest_asyncio.fixture
async def session_factory():#session_factory 管"库从哪来、数据怎么种"
    """每个测试一个全新的内存库，并把 sessionmaker 交给测试自己用。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSession = async_sessionmaker(engine, expire_on_commit=False)

    async with TestSession() as session:
        area = Area(name="A 区·测试", description="单元测试用区域")
        area.seats = [Seat(code=f"A-{i:02d}", has_power=(i % 2 == 1)) for i in range(1, 4)]
        session.add(area)
        await session.commit()

    yield TestSession

    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):#client 管"HTTP 请求走哪个库"
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

@pytest_asyncio.fixture
async def headers(client) -> dict[str, str]:
    """注册并登录一个测试用户，返回可直接放进请求的 Authorization 头。"""
    return await register_and_login(client)
