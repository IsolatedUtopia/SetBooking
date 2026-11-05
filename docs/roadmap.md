# SetBooking 四周作战地图

> 这份文档是**你照着操作的路线图**，不是成品代码库。每一节的代码都带"为什么"，先读懂再敲进去。
> 设计原理详见 `E:\DeepseekHarness\docs\seat-booking-implementation-guide.md`（14 节，讲建模对比、并发时序、状态机）。

---

## 0. 全景图

| 周 | 主题 | 产出 | 验收标准 |
| --- | --- | --- | --- |
| W1 | 骨架 → 能预约 | 5 张表、JWT、预约创建/取消、pytest | `pytest` 全绿；两个请求同时抢同一座位，一个 201 一个 409 |
| W2 | 并发与自动化 | Redis 锁、签到、超时释放、Locust 压测 | 压测报告：加锁前后 409 率对比 |
| W3 | 后台与工程质量 | Django Admin、GitHub Actions、覆盖率 | CI 绿；后台能改座位/看预约 |
| W4 | 上线 | Docker Compose、Nginx、云部署、README | 公网 URL 能打开 `/docs` |

**W1 拆成四天**（每天 2–3 小时，能跑起来才进下一天）：

| 天 | 做什么 | 结束时的状态 |
| --- | --- | --- |
| Day 1 | 应用骨架 + `/health` | `uvicorn` 能起，浏览器看到 `{"status":"ok"}` |
| Day 2 | 配置、数据库连接、5 张表、Alembic 迁移 | `alembic upgrade head` 建出表；`/health` 能查库 |
| Day 3 | 注册、登录、JWT、`/users/me` | 用 Swagger 能注册+登录+拿 token 访问受保护接口 |
| Day 4 | 预约创建/取消 + 并发测试 | `pytest` 全绿，含并发 409 测试 |

---

## 1. 依赖补齐（Day 2 开始前执行一次）

Day 1 装的 7 个包不够，补齐数据库与鉴权相关：

```powershell
pip install "sqlalchemy[asyncio]" aiomysql aiosqlite alembic pyjwt bcrypt python-multipart -i https://pypi.tuna.tsinghua.edu.cn/simple
pip freeze | Set-Content -Encoding ascii requirements.txt
```

各是干什么的：

| 包 | 作用 |
| --- | --- |
| `sqlalchemy[asyncio]` | ORM + 异步支持（`greenlet` 由 `[asyncio]` 带进来） |
| `aiomysql` | MySQL 的异步驱动（纯 Python，Windows/3.14 不用编译） |
| `aiosqlite` | SQLite 的异步驱动，本地开发和单测用它，免装 MySQL |
| `alembic` | 数据库迁移工具（SQLAlchemy 官方） |
| `pyjwt` | 签发/校验 JWT |
| `bcrypt` | 密码哈希 |
| `python-multipart` | 让 FastAPI 能解析表单（`/auth/login` 用 OAuth2 表单格式，没有它会报 422） |

> **为什么先 SQLite 后 MySQL**：你本机 MySQL80 在跑但密码未知。开发阶段用 SQLite 文件库（`dev.db`），零配置；等 Day 4 要验证"真并发"时再切 MySQL。切换只改 `.env` 一行，代码不用动——这就是把连接串放配置里的意义。

---

## 2. Day 1：骨架与 `/health`

### 2.1 目录

```
SetBooking/
├── app/
│   ├── __init__.py
│   ├── main.py            # 装配层：只创建 app、挂路由
│   └── api/
│       ├── __init__.py
│       └── health.py      # 第一个路由模块
├── requirements.txt
├── .gitignore
└── .venv/                 # 不进仓库
```

```powershell
New-Item -ItemType Directory -Force app\api
New-Item -ItemType File -Force app\__init__.py, app\api\__init__.py
```

### 2.2 `app/api/health.py`

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

- `APIRouter` 是"路由集合"，不是 app。它先攒端点，最后由 `main.py` 统一挂载。
- 返回类型标注 `-> dict[str, str]` 会被 FastAPI 拿去生成响应 schema，`/docs` 里可见。**标注是契约，不是装饰**。

### 2.3 `app/main.py`

```python
from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(title="SetBooking", version="0.1.0")

app.include_router(health_router)
```

`main.py` 永远只做装配。**看到有人在这里写业务逻辑，就是分层破了。**

### 2.4 运行与验收

```powershell
uvicorn app.main:app --reload --port 8000
```

- http://127.0.0.1:8000/health → `{"status":"ok"}`
- http://127.0.0.1:8000/docs → Swagger UI，自动生成，不用写文档

```powershell
git add -A
git commit -m "feat: 搭建应用骨架并添加健康检查接口"
git push
```

---

## 3. Day 2：配置、数据库、5 张表

### 3.1 这一天的核心是**表设计**，不是写代码

先把 10 条业务规则写成句子（写进 README，它们同时是测试用例清单）：

1. 营业时间 08:00–22:00，每 30 分钟一个时段，共 28 段
2. 一次预约 1–4 个**连续**时段
3. 只能约**今天和未来 6 天**（7 天窗口）
4. 同一座位同一时段只能被一个人占用 ← **唯一的硬不变量**
5. 每人每天最多 2 单
6. 自己的时段不能与自己重叠
7. 开始前 15 分钟可签到，签到后状态变 CHECKED_IN
8. 开始后 30 分钟未签到的 PENDING 自动释放为 NO_SHOW
9. 取消即释放，座位可被别人约
10. 累计 3 次 NO_SHOW 封禁 7 天

**第 4 条决定表结构**：把一个预约"展开"成时段明细行，每行一个 `(seat_id, date, slot_index)`，在这三列上建**唯一索引**。这样超卖在数据库层就不可能发生——两个并发请求里必有一个插入失败。

这就是本项目最值钱的设计决策。对比：用 `start_time/end_time` 区间存储，MySQL 没有 exclusion 约束，只能靠应用层判重，正是超卖的来源。

### 3.2 五张表

```
users             id, student_no(唯一), email(唯一), hashed_password, full_name,
                  is_admin, no_show_count, banned_until, created_at
areas             id, name(唯一), floor, open_time, close_time, created_at
seats             id, area_id(FK), code, has_power, is_active
                  UNIQUE(area_id, code)
reservations      id, user_id(FK), seat_id(FK), date, start_slot, end_slot,
                  status(PENDING/CHECKED_IN/COMPLETED/CANCELLED/NO_SHOW),
                  checked_in_at, created_at
reservation_slots id, reservation_id(FK), seat_id, date, slot_index
                  UNIQUE(seat_id, date, slot_index)   ← 防超卖的根
```

`reservation_slots` 是"冗余"设计，但这不是冗余，是**把并发冲突交给数据库**的代价。取消时删掉明细行即释放座位。

### 3.3 `app/core/config.py`

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SetBooking"
    api_prefix: str = "/api/v1"
    debug: bool = True

    # 本地开发用 SQLite；切 MySQL 时只改这一行
    database_url: str = "sqlite+aiosqlite:///./dev.db"

    jwt_secret: str = "dev-only-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    slot_minutes: int = 30
    day_start_hour: int = 8
    day_end_hour: int = 22
    max_slots_per_reservation: int = 4
    max_reservations_per_day: int = 2
    booking_window_days: int = 7
    check_in_lead_minutes: int = 15
    no_show_release_minutes: int = 30
    max_no_show_before_ban: int = 3
    ban_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

`.env`（**不进 Git**，`.gitignore` 里已有 `.env`）：

```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
JWT_SECRET=换成你自己的随机串
```

`lru_cache` 让配置在整个进程里只解析一次。**为什么用 pydantic-settings 而不是 `os.getenv`**：字段有类型、有默认值、缺必填项时启动就报错，而不是跑到半夜才 `NoneType` 崩。

### 3.4 `app/db/base.py` 与 `app/db/session.py`

```python
# app/db/base.py
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 统一命名规则，否则不同数据库自动生成的约束名不一致，迁移会出错
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

```python
# app/db/session.py
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    async with SessionLocal() as session:
        yield session
```

`expire_on_commit=False` 很关键：默认情况下 commit 后对象属性会过期，异步环境下再去读会触发 `MissingGreenlet` 报错。设为 False 后 commit 完还能直接读。

### 3.5 模型（`app/models/`）

```python
# app/models/user.py
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(64))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    no_show_count: Mapped[int] = mapped_column(Integer, default=0)
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
```

```python
# app/models/area.py
from sqlalchemy import Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    floor: Mapped[int] = mapped_column(Integer, default=1)
    open_hour: Mapped[int] = mapped_column(Integer, default=8)
    close_hour: Mapped[int] = mapped_column(Integer, default=22)

    seats: Mapped[list["Seat"]] = relationship(back_populates="area", lazy="selectin")
```

```python
# app/models/seat.py
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (UniqueConstraint("area_id", "code", name="uq_seats_area_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(16))
    has_power: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    area: Mapped["Area"] = relationship(back_populates="seats", lazy="selectin")
```

```python
# app/models/reservation.py
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# 占用座位的状态：只有这两个"活着"
OCCUPYING_STATUSES = (ReservationStatus.PENDING, ReservationStatus.CHECKED_IN)


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    start_slot: Mapped[int] = mapped_column(Integer)
    end_slot: Mapped[int] = mapped_column(Integer)  # 闭区间
    status: Mapped[str] = mapped_column(String(16), default=ReservationStatus.PENDING, index=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    slots: Mapped[list["ReservationSlot"]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan", lazy="selectin"
    )


class ReservationSlot(Base):
    """把一个预约展开成时段明细。唯一索引让并发超卖在数据库层不可能发生。"""

    __tablename__ = "reservation_slots"
    __table_args__ = (
        UniqueConstraint("seat_id", "date", "slot_index", name="uq_reservation_slots_seat_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), index=True
    )
    seat_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[date] = mapped_column(Date)
    slot_index: Mapped[int] = mapped_column(Integer)

    reservation: Mapped["Reservation"] = relationship(back_populates="slots")
```

`app/models/__init__.py` 里把四个模型都导入，这样 Alembic 的 autogenerate 才能看到它们：

```python
from app.models.area import Area
from app.models.reservation import Reservation, ReservationSlot, ReservationStatus
from app.models.seat import Seat
from app.models.user import User

__all__ = ["Area", "Reservation", "ReservationSlot", "ReservationStatus", "Seat", "User"]
```

### 3.6 Alembic 初始化

```powershell
alembic init alembic
```

会生成 `alembic.ini` 和 `alembic/` 目录。然后改两处：

**① `alembic.ini` 里把 url 留空**（真正的地址从代码配置读，避免密码写进配置文件）：

```ini
sqlalchemy.url =
```

**② 重写 `alembic/env.py`**（异步版本）：

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.base import Base
from app import models  # noqa: F401  必须导入，否则 autogenerate 看不到表

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=settings.database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`render_as_batch=True`（SQLite 时才开）是因为 SQLite 不支持 `ALTER TABLE` 改列，Alembic 用"建新表+拷数据+换名"的方式来模拟，batch 模式就是在做这件事。MySQL 上不需要。

### 3.7 生成并执行迁移

```powershell
alembic revision --autogenerate -m "init tables"
alembic upgrade head
```

**看完生成的迁移文件再执行**——autogenerate 是"建议"，不是"答案"：检查唯一约束 `uq_reservation_slots_seat_slot` 在不在、索引是否齐全。这是真实工作里必做的一步，直接 `upgrade` 不看文件的人迟早出事。

验证表建出来了（SQLite）：

```powershell
python -c "import sqlite3; c=sqlite3.connect('dev.db'); print(c.execute(\"select name from sqlite_master where type='table'\").fetchall())"
```

### 3.8 把 `/health` 升级成真检查

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "database": f"error: {exc.__class__.__name__}"}
    return {"status": "ok", "database": "ok"}
```

**永远返回 ok 的健康检查是假健康检查。** 它能替你看出"数据库连不上"——这是上线后最常见的故障。

### 3.9 Day 2 提交

```powershell
git add -A
git commit -m "feat: 添加配置、数据库连接与 5 张表模型及迁移"
git push
```

验收：`alembic upgrade head` 无报错；`/health` 返回 `{"status":"ok","database":"ok"}`；`git status` 干净。

---

## 4. Day 3：注册、登录、JWT

### 4.1 思路

- 密码**永远不存明文**，存 bcrypt 哈希；校验时用 `checkpw`
- 登录成功返回 JWT，客户端后续请求带 `Authorization: Bearer <token>`
- token 里放 `sub`（用户 id）和 `exp`（过期时间），**不放敏感信息**——JWT 只是 base64，谁都能解出内容
- 受保护接口靠依赖注入 `get_current_user` 统一鉴权，不在每个函数里重复写

### 4.2 `app/core/security.py`

```python
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode()[:72], hashed.encode())


def create_access_token(subject: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return int(payload["sub"])
```

`encode()[:72]`：bcrypt 只处理前 72 字节，超长会直接抛异常（bcrypt 4.x 起），截断是为了行为可预期。

### 4.3 `app/schemas/user.py` 与 `auth.py`

```python
import re

from pydantic import BaseModel, ConfigDict, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserRegister(BaseModel):
    student_no: str
    email: str
    password: str
    full_name: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少 8 位")
        return v


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_no: str
    email: str
    full_name: str
    is_admin: bool
```

```python
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

`from_attributes=True` 让 Pydantic 能直接从 SQLAlchemy 对象读属性，不用手动拼字典。

> 为什么不用 `EmailStr`：它需要额外装 `email-validator`，多一个依赖。自己写正则够用，也更容易讲清楚"校验在哪一层做"。

### 4.4 `app/api/deps.py`

```python
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    user_id = decode_access_token(token)  # 无效/过期会抛异常，下一步统一处理
    user = await session.get(User, user_id)
    if user is None:
        from app.core.exceptions import UnauthorizedError

        raise UnauthorizedError("用户不存在")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
```

`oauth2_scheme` 同时做两件事：从 `Authorization` 头取 token，并让 Swagger 的 **Authorize** 按钮生效。

### 4.5 统一异常（`app/core/exceptions.py`）

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "bad_request"):
        self.message = message
        self.status_code = status_code
        self.code = code


class BadRequestError(AppError):
    def __init__(self, message: str):
        super().__init__(message, 400, "bad_request")


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未认证"):
        super().__init__(message, 401, "unauthorized")


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权限"):
        super().__init__(message, 403, "forbidden")


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, 404, "not_found")


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__(message, 409, "conflict")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )
```

**为什么不用 `HTTPException`**：`HTTPException` 把"HTTP 语义"和"业务语义"绑在一起，service 层就得 `import fastapi`。抛出领域异常由 API 层翻译，分层才干净。同时客户端拿到的是固定结构 `{code, message}`，前端不用猜。

### 4.6 `app/api/auth.py`

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select

from app.api.deps import SessionDep
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.user import UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserRegister, session: SessionDep) -> User:
    exists = await session.scalar(
        select(User).where(or_(User.email == payload.email, User.student_no == payload.student_no))
    )
    if exists is not None:
        raise ConflictError("邮箱或学号已被注册")

    user = User(
        student_no=payload.student_no,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
) -> Token:
    # OAuth2 标准里这个字段叫 username，允许填邮箱或学号
    user = await session.scalar(
        select(User).where(or_(User.email == form.username.lower(), User.student_no == form.username))
    )
    if user is None or not verify_password(form.password, user.hashed_password):
        raise UnauthorizedError("账号或密码错误")

    return Token(access_token=create_access_token(user.id))
```

**注意这里没做"先查后写"的防重竞争**：两个人同时用同一邮箱注册，可能都通过检查。所以 `email`/`student_no` 上必须有唯一约束，注册要捕获 `IntegrityError` 翻译成 409。**同一套思路贯穿全项目：约束在数据库，代码只是翻译错误。**

### 4.7 `app/api/users.py`

```python
from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.user import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
```

### 4.8 挂载

`app/api/router.py`：

```python
from fastapi import APIRouter

from app.api import auth, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
```

`app/main.py` 加上：

```python
from app.api.router import api_router
from app.api.health import router as health_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers

app = FastAPI(title=settings.app_name, version="0.1.0")
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_prefix)
```

### 4.9 Day 3 验收

在 `/docs` 里依次操作：

1. `POST /api/v1/auth/register` 建一个用户 → 201
2. 再提交同样的邮箱 → 409 `{"code":"conflict",...}`
3. `POST /api/v1/auth/login`（**表单格式**，`username` 填邮箱）→ 拿到 `access_token`
4. 点右上角 **Authorize**，粘贴 token → 访问 `GET /api/v1/users/me` → 返回自己的信息
5. 不填 token 访问 `/users/me` → 401

```powershell
git add -A
git commit -m "feat: 实现注册登录与 JWT 鉴权"
git push
```

---

## 5. Day 4：预约闭环 + 并发测试

### 5.1 时段模型

```python
# app/core/slots.py
from datetime import time

from app.core.config import settings


def slots_per_day() -> int:
    return (settings.day_end_hour - settings.day_start_hour) * 60 // settings.slot_minutes


def slot_to_time(slot_index: int) -> time:
    minutes = settings.day_start_hour * 60 + slot_index * settings.slot_minutes
    return time(hour=minutes // 60, minute=minutes % 60)


def slot_label(slot_index: int) -> str:
    start = slot_to_time(slot_index)
    end_minutes = settings.day_start_hour * 60 + (slot_index + 1) * settings.slot_minutes
    return f"{start:%H:%M}-{end_minutes // 60:02d}:{end_minutes % 60:02d}"
```

**用 `date + slot_index` 而不是两个 `datetime`**：跨时区、夏令时、精度问题全部消失，唯一索引也更好写。

### 5.2 `app/schemas/reservation.py`

```python
from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator


class ReservationCreate(BaseModel):
    seat_id: int
    date: date
    start_slot: int
    end_slot: int

    @model_validator(mode="after")
    def check_range(self) -> "ReservationCreate":
        if self.end_slot < self.start_slot:
            raise ValueError("结束时段不能早于开始时段")
        if self.end_slot - self.start_slot + 1 > 4:
            raise ValueError("一次最多预约 4 个时段")
        return self


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seat_id: int
    date: date
    start_slot: int
    end_slot: int
    status: str
```

### 5.3 `app/services/reservation.py` —— 全项目最核心的 60 行

```python
from datetime import UTC, date as date_type, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.reservation import OCCUPYING_STATUSES, Reservation, ReservationSlot
from app.models.seat import Seat
from app.models.user import User
from app.schemas.reservation import ReservationCreate

TZ = "Asia/Shanghai"


def _today() -> date_type:
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    return dt.now(ZoneInfo(TZ)).date()


async def create_reservation(
    session: AsyncSession, user: User, payload: ReservationCreate
) -> Reservation:
    now = datetime.now(UTC)

    # 1. 封禁
    if user.banned_until is not None and user.banned_until > now:
        raise ForbiddenError("你因爽约过多被暂时封禁")

    # 2. 日期窗口
    today = _today()
    if payload.date < today:
        raise BadRequestError("不能预约过去的日期")
    if payload.date > today + timedelta(days=settings.booking_window_days - 1):
        raise BadRequestError(f"只能预约未来 {settings.booking_window_days} 天")

    # 3. 时段范围
    total = (settings.day_end_hour - settings.day_start_hour) * 60 // settings.slot_minutes
    if payload.start_slot < 0 or payload.end_slot >= total:
        raise BadRequestError("时段超出营业时间")
    if payload.date == today:
        # 今天已经开始的时段不能约
        current_slot = (
            (datetime.now().hour - settings.day_start_hour) * 60 // settings.slot_minutes
        )
        if payload.start_slot <= current_slot:
            raise BadRequestError("该时段已经开始，不能预约")

    # 4. 座位存在
    seat = await session.get(Seat, payload.seat_id)
    if seat is None or not seat.is_active:
        raise NotFoundError("座位不存在或已停用")

    # 5. 每人每天单数上限
    count = await session.scalar(
        select(func.count()).select_from(Reservation).where(
            Reservation.user_id == user.id,
            Reservation.date == payload.date,
            Reservation.status.in_(OCCUPYING_STATUSES),
        )
    )
    if (count or 0) >= settings.max_reservations_per_day:
        raise BadRequestError(f"每天最多预约 {settings.max_reservations_per_day} 次")

    # 6. 自己时段不重叠（这个可以查，因为只涉及自己，不会并发）
    overlap = await session.scalar(
        select(func.count()).select_from(Reservation).where(
            Reservation.user_id == user.id,
            Reservation.date == payload.date,
            Reservation.status.in_(OCCUPYING_STATUSES),
            Reservation.start_slot <= payload.end_slot,
            Reservation.end_slot >= payload.start_slot,
        )
    )
    if (overlap or 0) > 0:
        raise ConflictError("与你已有的预约时间重叠")

    # 7. 建单 + 展开明细；唯一索引是最后一道防线
    reservation = Reservation(
        user_id=user.id,
        seat_id=payload.seat_id,
        date=payload.date,
        start_slot=payload.start_slot,
        end_slot=payload.end_slot,
    )
    session.add(reservation)
    await session.flush()  # 拿到 reservation.id

    for slot_index in range(payload.start_slot, payload.end_slot + 1):
        session.add(
            ReservationSlot(
                reservation_id=reservation.id,
                seat_id=payload.seat_id,
                date=payload.date,
                slot_index=slot_index,
            )
        )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_reservation_slots_seat_slot" in str(exc.orig) or "UNIQUE constraint failed" in str(exc.orig):
            raise ConflictError("该座位在你选择的时段已被预约") from exc
        raise
    await session.refresh(reservation)
    return reservation


async def cancel_reservation(session: AsyncSession, user: User, reservation_id: int) -> None:
    reservation = await session.get(Reservation, reservation_id)
    if reservation is None:
        raise NotFoundError("预约不存在")
    if reservation.user_id != user.id:
        raise ForbiddenError("不能取消别人的预约")
    if reservation.status not in ("PENDING", "CHECKED_IN"):
        raise BadRequestError("该预约已结束，无需取消")

    reservation.status = "CANCELLED"
    # 删明细行 = 释放座位。不删的话唯一索引还占着，别人永远约不到
    for slot in list(reservation.slots):
        await session.delete(slot)
    await session.commit()
```

**讲解要点，面试会问**：

- 第 5、6 步是 `SELECT COUNT` 再插入，这叫 **check-then-act**，两个请求同时进来时可能都通过——**所以它不能保证正确性**，只能挡住绝大多数正常场景。
- 真正的保证是第 7 步的唯一索引：数据库对索引加锁，两个插入串行化，后者 `IntegrityError`。
- 代码的责任是**把数据库的拒绝翻译成人话**（409 + 具体原因），而不是自己重新发明并发控制。
- 顺序很重要：先 `flush` 拿到主键，再插明细，最后一次性 commit。

### 5.4 `app/api/reservations.py`

```python
from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas.reservation import ReservationCreate, ReservationRead
from app.services import reservation as reservation_service

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("", response_model=ReservationRead, status_code=201)
async def create(
    payload: ReservationCreate, user: CurrentUser, session: SessionDep
) -> ReservationRead:
    reservation = await reservation_service.create_reservation(session, user, payload)
    return ReservationRead.model_validate(reservation)


@router.delete("/{reservation_id}", status_code=204)
async def cancel(reservation_id: int, user: CurrentUser, session: SessionDep) -> None:
    await reservation_service.cancel_reservation(session, user, reservation_id)
```

### 5.5 测试（`tests/`）

`tests/conftest.py`：

```python
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_session
from app.main import app


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
```

`pyproject.toml` 里加：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**必写的 5 个测试**：

```python
async def test_register_and_login(client): ...
async def test_duplicate_slot_returns_409(client): ...   # 核心：同一座位同一时段第二次 409
async def test_invalid_slot_range(client): ...            # end < start、超过 4 段、超出营业时间
async def test_booking_window(client): ...                # 昨天 400、第 8 天 400
async def test_cancel_releases_seat(client): ...          # 取消后别人能约到同一座位
```

第 2 个测试是简历 bullet 的支撑："通过唯一索引 + 冲突翻译保证同座同时段不超卖，测试覆盖并发场景"。

### 5.6 Day 4 验收

```powershell
pytest -q
ruff check .
git add -A
git commit -m "feat: 实现预约创建取消与防超卖唯一索引"
git push
```

全绿才算 W1 完成。

---

## 6. W2：并发与自动化（概要）

| 任务 | 要点 | 产出 |
| --- | --- | --- |
| 签到接口 | `POST /reservations/{id}/checkin`；只允许开始前 15 分到开始后 30 分；状态 PENDING→CHECKED_IN | 状态机测试 |
| 超时释放 | APScheduler 每分钟扫 `status=PENDING AND 开始时间+30min < now` → NO_SHOW + 删明细 + `no_show_count += 1` | 定时任务日志 |
| Redis 分布式锁 | `SET key value NX PX 5000` 包住"查占用+插入"；key = `lock:seat:{seat_id}:{date}:{slot}` | 加锁前后对比 |
| Locust 压测 | 100 并发抢同一座位的同一时段，统计 201/409 数量 | 报告：0 超卖 |
| 缓存 | 座位日历（区域+日期）缓存 60s，取消时删 key | 命中率 |

**W2 的真正价值**：让你能说出"没有唯一索引时超卖率 X%，加上后 0%，Redis 锁把 P99 从 Y ms 降到 Z ms"——**数字才是简历上的东西**。

---

## 7. W3：Django Admin + CI

- 新建 `admin_site/`（独立 Django 项目，连同一个 MySQL 库），用 `inspectdb` 逆向生成模型，注册到 admin
- 两个进程同一个库：FastAPI 管业务 API，Django Admin 管运营（改座位、看预约、封禁用户）
- GitHub Actions：ruff + pytest + 服务容器 mysql:8.0 + `alembic upgrade head`
- 覆盖率 `pytest --cov=app --cov-report=term-missing`，目标 75%+

**为什么值得做**：JD 里同时出现 Django 和 FastAPI 时，你能说"主 API 用 FastAPI 保证性能，运营后台用 Django Admin 省下两周开发时间"，这是**技术选型判断力**，比"两个框架我都用过"值钱得多。

---

## 8. W4：上线

- `Dockerfile`（python:3.12-slim，非 root 用户）
- `docker-compose.yml`：mysql + redis + api + nginx
- 部署到一台云服务器（阿里云/腾讯云学生机），域名 + HTTPS（Caddy 或 certbot）
- README：架构图、接口表、压测数据、部署步骤、**踩坑记录**
- 简历 bullet（三条，全部可量化）：
  1. 基于 FastAPI + SQLAlchemy 2.0 async 实现自习室预约系统，5 张表、12 个接口，JWT 鉴权
  2. 用"预约展开为时段明细 + 唯一索引"解决并发超卖，Locust 100 并发压测 0 超卖
  3. Django Admin 搭建运营后台，GitHub Actions 全流程 CI，测试覆盖率 78%

---

## 9. 常见坑（提前知道省两天）

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| `MissingGreenlet` | commit 后读已过期对象 | `expire_on_commit=False`，或 `refresh()` |
| `sqlalchemy.exc.InvalidRequestError: greenlet_spawn has not been called` | 在同步上下文里用了 lazy load | 关系用 `lazy="selectin"`，或显式 `selectinload` |
| SQLite 下唯一约束不生效 | 用 `create_all` 建表但模型改了没重建 | 删 `dev.db` 重跑 `upgrade head` |
| Alembic 生成空迁移 | `env.py` 没 import models | `from app import models  # noqa` |
| 401 但 token 明明对 | `sub` 存成 int，PyJWT 2.x 要求字符串 | `str(user_id)` |
| 并发测试测不出问题 | SQLite 单写者，天然串行 | 并发测试必须连 MySQL |
| `uvicorn` 启动后 404 | 路由前缀写错，或忘了 `include_router` | 看 `/docs` 有没有那个端点 |
| pip 装包超时 | 直连 PyPI 不稳 | `-i https://pypi.tuna.tsinghua.edu.cn/simple` |

---

## 10. 每天结束的检查清单

```powershell
pytest -q          # 全绿？
ruff check .       # 无告警？
git status         # 干净？
git log --oneline  # 今天有 2-4 个有意义的提交？
```

四个都过，今天就结束。**不要留"明天再提交"的改动**——那是最容易丢的东西。
