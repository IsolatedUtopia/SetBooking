import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import settings
from app.tasks import release_no_show_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用启动时开调度器，关闭时收掉。"""
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        release_no_show_job,
        trigger=IntervalTrigger(seconds=settings.no_show_scan_seconds),
        id="release-no-show",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info("定时任务已启动：每 %s 秒扫描一次超时未签到", settings.no_show_scan_seconds)

    # 启动时先补扫一次：服务刚起来就把"欠的账"还掉
    await release_no_show_job()

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_prefix)
