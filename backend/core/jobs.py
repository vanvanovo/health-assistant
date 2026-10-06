# backend/core/jobs.py
# 四类主动服务任务:打卡提醒 / 每日简报 / 周报 / 异常预警。
# 纪律:全部幂等(msg_key)+ 触发前复检(计划/数据以实时查询为准);单任务失败不影响其他任务。

from __future__ import annotations

from datetime import date, timedelta

from backend.agents.common import tools
from backend.core import alerts, notify_store, reporter
from backend.core.logger import get_logger

logger = get_logger(__name__)


def _parse_day(s: str | None) -> date:
    if s:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    return date.today()


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def job_checkin_remind(day: str | None = None) -> dict:
    """打卡提醒:今日仍有待打卡项 → 站内信(触发前实时复检)。"""
    d = _parse_day(day)
    plan = tools.tool_data(await tools.call_tool("get_active_plan", {"date": d.isoformat()}), {}) or {}
    pending = [
        it for it in (plan.get("items") or [])
        if it.get("date") == d.isoformat() and it.get("status") == "pending"
    ]
    if not pending:
        return {"job": "remind", "status": "skipped", "reason": "今日没有待打卡的计划项"}
    minutes = sum(int(it.get("est_minutes") or 20) for it in pending)
    body = (
        f"今天还有 {len(pending)} 项没打卡:"
        + "、".join(str(it.get("title")) for it in pending[:3])
        + f",预计 {minutes} 分钟。加油~"
    )
    msg = await notify_store.add_message(
        "checkin_remind", "今日打卡提醒", body, f"remind:{d.isoformat()}",
        payload={"items": [{"id": it.get("id"), "title": it.get("title")} for it in pending]},
    )
    return {"job": "remind", "status": "sent" if msg else "duplicate", "message_id": (msg or {}).get("id")}


async def job_daily_brief(day: str | None = None) -> dict:
    """每日简报:今日完成度 + 明日安排 + 一句建议;落报告 + 站内信。"""
    d = _parse_day(day)
    key = f"brief:{d.isoformat()}"
    if await notify_store.message_exists(key):
        return {"job": "brief", "status": "duplicate"}
    rep = await reporter.build_daily_brief(d)
    saved = await notify_store.save_report("daily", d.isoformat(), d.isoformat(), rep["content"], rep["facts"])
    msg = await notify_store.add_message(
        "brief", "每日简报", rep["content"], key, payload={"report_id": (saved or {}).get("id")}
    )
    return {
        "job": "brief", "status": "sent" if msg else "duplicate",
        "report_id": (saved or {}).get("id"), "message_id": (msg or {}).get("id"),
    }


async def job_weekly_report(week_start: str | None = None) -> dict:
    """周报:默认本周(周一);落报告 + 站内信。"""
    ws = _monday(_parse_day(week_start)) if week_start else _monday(date.today())
    key = f"weekly:{ws.isoformat()}"
    if await notify_store.message_exists(key):
        return {"job": "weekly", "status": "duplicate"}
    rep = await reporter.build_weekly_report(ws)
    saved = await notify_store.save_report(
        "weekly", ws.isoformat(), (ws + timedelta(days=6)).isoformat(), rep["content"], rep["facts"]
    )
    msg = await notify_store.add_message(
        "weekly", f"周报({ws.isoformat()} 起)", rep["content"], key,
        payload={"report_id": (saved or {}).get("id")},
    )
    return {
        "job": "weekly", "status": "sent" if msg else "duplicate",
        "report_id": (saved or {}).get("id"), "message_id": (msg or {}).get("id"),
    }


async def job_alerts(day: str | None = None) -> dict:
    """异常预警:规则命中即报;同规则 48h 防重。"""
    d = _parse_day(day)
    d_from = d - timedelta(days=alerts.HISTORY_DAYS - 1)
    recs = tools.tool_data(
        await tools.call_tool(
            "query_records",
            {"date_from": d_from.isoformat(), "date_to": d.isoformat(), "limit": 60},
        ),
        {},
    ) or {}
    summary = tools.tool_data(
        await tools.call_tool(
            "get_range_summary", {"date_from": d_from.isoformat(), "date_to": d.isoformat()}
        ),
        {},
    ) or {}
    records = recs.get("records") or []
    rate = (summary.get("checkin") or {}).get("completion_rate")
    hits = alerts.evaluate_alerts(records, rate, d)

    sent = []
    for a in hits:
        yesterday_key = f"alert:{a['rule']}:{(d - timedelta(days=1)).isoformat()}"
        if await notify_store.message_exists(yesterday_key):
            continue  # 48h 防重:昨天报过的规则今天不重复
        msg = await notify_store.add_message(
            "alert", f"预警:{a['rule']}", a["message"], f"alert:{a['rule']}:{d.isoformat()}",
            payload={"rule": a["rule"], "level": a["level"], "evidence": alerts.alert_evidence(records, d)},
        )
        if msg:
            sent.append({"rule": a["rule"], "level": a["level"], "message_id": msg["id"]})
    return {"job": "alert", "status": "sent" if sent else "none", "alerts": sent}


JOBS = {
    "remind": job_checkin_remind,
    "brief": job_daily_brief,
    "weekly": job_weekly_report,
    "alert": job_alerts,
}
