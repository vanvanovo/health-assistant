# backend/api/v1/dashboard.py
# 数据看板:overview / trends / heatmap / radar。
# P10:聚合结果走 Redis 60s 缓存(Redis 不可用透明降级直查,不阻塞)。

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from backend.agents.common import tools
from backend.core import cache
from backend.core.stats import compute_radar
from backend.dependencies import get_current_user

router = APIRouter(prefix="/dashboard", tags=["看板"])


def _parse_date(s: str | None) -> date:
    if s:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    return date.today()


async def _cached(key: str, producer):
    """读缓存 → 未命中计算并回填(60s);Redis 不可用由 cache 层透明降级。"""
    hit = await cache.cache_get(key)
    if hit is not None:
        return hit
    data = await producer()
    await cache.cache_set(key, data)
    return data


@router.get("/overview")
async def overview(date_str: str | None = Query(None, alias="date"), user: dict = Depends(get_current_user)):
    """指标卡:最新体重 + 近 7 天训练/睡眠/体感/完成率。"""
    today = _parse_date(date_str)

    async def _produce():
        d_from = (today - timedelta(days=6)).isoformat()
        d_to = today.isoformat()
        summary = tools.tool_data(
            await tools.call_tool("get_range_summary", {"date_from": d_from, "date_to": d_to}), {}
        ) or {}
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
            "streak_days": None,
        }

    return await _cached(f"cache:dash:overview:{today.isoformat()}", _produce)


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

    async def _produce():
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

    return await _cached(f"cache:dash:trends:{d1.isoformat()}:{d2.isoformat()}", _produce)


@router.get("/heatmap")
async def heatmap(days: int = Query(90, ge=7, le=180), user: dict = Depends(get_current_user)):
    """近 N 天热力图数据:每天训练分钟 + 打卡完成数(前端可切换)。"""
    today = date.today()

    async def _produce():
        d_from = today - timedelta(days=days - 1)
        data = tools.tool_data(
            await tools.call_tool(
                "get_daily_stats", {"date_from": d_from.isoformat(), "date_to": today.isoformat()}
            ),
            {},
        ) or {}
        return {"from": d_from.isoformat(), "to": today.isoformat(), "days": data.get("days", [])}

    return await _cached(f"cache:dash:heatmap:{today.isoformat()}:{days}", _produce)


@router.get("/radar")
async def radar(weeks: int = Query(4, ge=1, le=8), user: dict = Depends(get_current_user)):
    """四维健康评分(运动/睡眠/饮食/恢复;规则加权,公式见 core/stats.py)。"""
    today = date.today()

    async def _produce():
        d_from = today - timedelta(days=weeks * 7 - 1)
        records = tools.tool_data(
            await tools.call_tool(
                "query_records",
                {"date_from": d_from.isoformat(), "date_to": today.isoformat(), "limit": 180},
            ),
            {},
        ) or {}
        meals = tools.tool_data(
            await tools.call_tool(
                "get_meal_summary", {"date_from": d_from.isoformat(), "date_to": today.isoformat()}
            ),
            {},
        ) or {}
        return compute_radar(records.get("records") or [], int(meals.get("days_recorded") or 0), weeks)

    return await _cached(f"cache:dash:radar:{today.isoformat()}:{weeks}", _produce)
