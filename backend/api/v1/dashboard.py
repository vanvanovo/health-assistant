# backend/api/v1/dashboard.py
# 数据看板:overview(指标卡)+ trends(多轴趋势)。数据与对话统计同口径(均走 MCP 规则聚合)。

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from backend.agents.common import tools
from backend.dependencies import get_current_user

router = APIRouter(prefix="/dashboard", tags=["看板"])


def _parse_date(s: str | None) -> date:
    if s:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    return date.today()


@router.get("/overview")
async def overview(date_str: str | None = Query(None, alias="date"), user: dict = Depends(get_current_user)):
    """指标卡:最新体重 + 近 7 天训练/睡眠/体感/完成率。"""
    today = _parse_date(date_str)
    d_from = (today - timedelta(days=6)).isoformat()
    d_to = today.isoformat()

    summary = tools.tool_data(await tools.call_tool("get_range_summary", {"date_from": d_from, "date_to": d_to}), {}) or {}
    records = tools.tool_data(
        await tools.call_tool("query_records", {"date_from": d_from, "date_to": d_to, "limit": 7}), {}
    ) or {}
    recs = records.get("records") or []
    latest = recs[-1] if recs else None
    return {
        "date": d_to,
        "weight_latest": latest.get("weight_kg") if latest else None,
        "weight_latest_date": latest.get("date") if latest else None,
        "workout_7d": summary.get("workout"),
        "sleep_7d": summary.get("sleep"),
        "feeling_7d": summary.get("feeling"),
        "checkin_7d": summary.get("checkin"),
        "streak_days": None,   # 连续打卡天数:P7 看板深化时计算
    }


@router.get("/trends")
async def trends(
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    user: dict = Depends(get_current_user),
):
    """多轴趋势:体重 / 训练时长 / 睡眠,按日升序。"""
    d1 = _parse_date(date_from)
    d2 = _parse_date(date_to)
    if d1 > d2:
        d1, d2 = d2, d1
    records = tools.tool_data(
        await tools.call_tool(
            "query_records", {"date_from": d1.isoformat(), "date_to": d2.isoformat(), "limit": 180}
        ),
        {},
    ) or {}
    series = [
        {
            "date": r.get("date"),
            "weight_kg": r.get("weight_kg"),
            "workout_minutes": r.get("workout_minutes") or 0,
            "sleep_hours": r.get("sleep_hours"),
        }
        for r in (records.get("records") or [])
    ]
    return {"from": d1.isoformat(), "to": d2.isoformat(), "series": series}
