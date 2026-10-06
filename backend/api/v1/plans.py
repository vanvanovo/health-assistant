# backend/api/v1/plans.py
# 计划查询:当前周计划 + 完成率(供计划打卡页)。

from datetime import date

from fastapi import APIRouter, Depends, Query

from backend.agents.common import tools
from backend.dependencies import get_current_user

router = APIRouter(prefix="/plans", tags=["计划"])


@router.get("/current")
async def current_plan(date_str: str | None = Query(None, alias="date"), user: dict = Depends(get_current_user)):
    """当前(或指定日期所在)周计划 + 明细 + 完成率。"""
    d = date_str[:10] if date_str else date.today().isoformat()
    plan = tools.tool_data(await tools.call_tool("get_active_plan", {"date": d}), {}) or {}
    if not plan:
        return {"plan": None, "progress": None}
    progress = tools.tool_data(
        await tools.call_tool("get_plan_progress", {"week_start": plan.get("week_start")}), {}
    ) or {}
    return {"plan": plan, "progress": progress}
