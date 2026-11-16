"""全局配置。

原则：所有"会变的数字和字符串"都集中在这里 —— 改配置，不改代码。
读取优先级：环境变量 > .env 文件 > 本文件里的默认值。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",      # .env 里多写的变量不会报错
    )

    # ---------- 应用 ----------
    app_name: str = "SetBooking"
    api_prefix: str = "/api/v1"
    debug: bool = True

    # ---------- 数据库 ----------
    # 本地：sqlite+aiosqlite:///./dev.db
    # 线上：mysql+aiomysql://user:pass@host:3306/dbname?charset=utf8mb4
    database_url: str = "sqlite+aiosqlite:///./dev.db"

    # ---------- 鉴权（Day 3 用） ----------
    jwt_secret: str = "dev-only-change-me-0123456789abcdef0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ---------- 业务规则 ----------
    slot_minutes: int = 30                    # 一个时段 30 分钟
    day_start_hour: int = 8                   # 08:00 开放
    day_end_hour: int = 22                    # 22:00 关门
    max_slots_per_reservation: int = 4        # 一次最多 4 个时段（2 小时）
    max_reservations_per_day: int = 2         # 每人每天最多 2 单
    booking_window_days: int = 7              # 只能约未来 7 天
    check_in_lead_minutes: int = 15           # 开始前 15 分钟可签到
    no_show_release_minutes: int = 30         # 开始后 30 分钟未签到自动释放
    max_no_show_before_ban: int = 3           # 爽约 3 次
    ban_days: int = 7                         # 封禁 7 天


@lru_cache
def get_settings() -> Settings:
    """整个进程只解析一次配置。"""
    return Settings()


settings = get_settings()