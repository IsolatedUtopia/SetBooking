"""后台定时任务：目前只有「超时未签到的自动释放」。"""

import logging

from app.db.session import SessionLocal
from app.services.reservation import release_no_shows

logger = logging.getLogger(__name__)


async def release_no_show_job() -> None:
    """跑一轮扫描。

    两件事必须做：
    1. 自己开一个 session（任务不是请求，没有 FastAPI 依赖注入）；
    2. 异常就地吞掉并记日志——任务抛出去会让调度器认为这一轮失败，
       但更重要的是不能因为一次数据库抖动就让整个调度器停摆。
    """
    try:
        async with SessionLocal() as session:
            await release_no_shows(session)
    except Exception:
        logger.exception("超时释放任务执行失败")
