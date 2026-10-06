# backend/core/scheduler.py
# APScheduler 定时任务(网关进程内,决策 D3):时间从画像 remind_times 读取,缺省 20:00 / 21:30 / 周日 21:00 / 09:00。
# 启动失败只降级告警,不阻塞网关(主动服务不可用不影响对话)。

from __future__ import annotations

from backend.core import jobs
from backend.core.logger import get_logger

logger = get_logger(__name__)

_scheduler = None

DEFAULT_TIMES = {"checkin": "20:00", "brief": "21:30", "weekly": "周日 21:00", "alert": "09:00"}
_WEEKDAY_MAP = {
    "周一": "mon", "周二": "tue", "周三": "wed", "周四": "thu",
    "周五": "fri", "周六": "sat", "周日": "sun", "周天": "sun",
}


def _hm(value: str, default_h: int, default_m: int) -> tuple[int, int]:
    text = str(value or "").strip()
    for part in text.split():
        if ":" in part:
            try:
                h, m = part.split(":", 1)
                return max(0, min(int(h), 23)), max(0, min(int(m), 59))
            except ValueError:
                continue
    return default_h, default_m


def _weekly(value: str) -> tuple[str, int, int]:
    h, m = _hm(value, 21, 0)
    dow = "sun"
    for cn, en in _WEEKDAY_MAP.items():
        if cn in str(value or ""):
            dow = en
            break
    return dow, h, m


async def _load_remind_times() -> dict:
    """读画像里的提醒时间;任何异常 → 全部缺省值。"""
    from sqlalchemy import select

    from backend.config import get_settings
    from backend.db import models as M
    from backend.db.base import get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            uid = (
                await session.execute(
                    select(M.User.id).where(M.User.username == get_settings().demo_username)
                )
            ).scalar_one_or_none()
            if uid:
                p = (await session.execute(select(M.Profile).where(M.Profile.user_id == uid))).scalars().first()
                rt = (p.remind_times or {}) if p else {}
                merged = dict(DEFAULT_TIMES)
                for k, v in rt.items():
                    if k in merged and isinstance(v, str) and v.strip():
                        merged[k] = v.strip()
                return merged
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler.remind_times_load_failed", error=str(e))
    return dict(DEFAULT_TIMES)


async def start_scheduler() -> bool:
    """装配并启动调度器;已启动/被禁用/失败 → 返回 False 或 True(幂等)。"""
    global _scheduler
    if _scheduler is not None:
        return True
    from backend.config import get_settings

    if not get_settings().jobs_enabled:
        logger.info("scheduler.disabled")
        return False
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        rt = await _load_remind_times()
        ch, cm = _hm(rt["checkin"], 20, 0)
        bh, bm = _hm(rt["brief"], 21, 30)
        wdow, wh, wm = _weekly(rt["weekly"])
        ah, am = _hm(rt["alert"], 9, 0)

        sched = AsyncIOScheduler()
        sched.add_job(jobs.job_checkin_remind, CronTrigger(hour=ch, minute=cm), id="checkin_remind", replace_existing=True)
        sched.add_job(jobs.job_daily_brief, CronTrigger(hour=bh, minute=bm), id="daily_brief", replace_existing=True)
        sched.add_job(jobs.job_weekly_report, CronTrigger(day_of_week=wdow, hour=wh, minute=wm), id="weekly_report", replace_existing=True)
        sched.add_job(jobs.job_alerts, CronTrigger(hour=ah, minute=am), id="alerts", replace_existing=True)
        sched.start()
        _scheduler = sched
        logger.info(
            "scheduler.started",
            checkin=f"{ch:02d}:{cm:02d}", brief=f"{bh:02d}:{bm:02d}",
            weekly=f"{wdow} {wh:02d}:{wm:02d}", alert=f"{ah:02d}:{am:02d}",
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler.start_failed", error=str(e))
        return False


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None


def scheduler_running() -> bool:
    return _scheduler is not None
