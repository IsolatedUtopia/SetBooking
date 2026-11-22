from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# 业务表统一存北京时间（Asia，无夏令时）。
# 时区在连接层钉死：不依赖宿主机/MySQL 服务的默认时区——
# 换一台机器时，行为必须完全一致。
_connect_args: dict[str, object] = {}
if settings.database_url.startswith("mysql"):
    _connect_args["init_command"] = "SET time_zone = '+08:00'"

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    async with SessionLocal() as session:
        yield session