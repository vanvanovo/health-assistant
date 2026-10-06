# backend/api/v1/memory.py
# 记忆:确认写入(签名 token)+ 事件管理(画像页/确认卡使用)。

import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.agents.common import tools
from backend.agents.memory.handler import apply_memory_token
from backend.dependencies import get_current_user

router = APIRouter(prefix="/memory", tags=["记忆"])


class ApplyRequest(BaseModel):
    token: str


@router.post("/apply")
async def apply(req: ApplyRequest, user: dict = Depends(get_current_user)):
    """确认写入:校验签名 token → 落库(画像 patch / 事件)。"""
    try:
        return await apply_memory_token(req.token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class EventRequest(BaseModel):
    kind: str
    description: str
    start_date: str
    end_date: str | None = None


@router.get("/events")
async def list_events(date_str: str | None = Query(None, alias="date"), user: dict = Depends(get_current_user)):
    """某天有效的事件列表(默认今天;画像页展示)。"""
    d = date_str[:10] if date_str else date.today().isoformat()
    return tools.tool_data(await tools.call_tool("list_active_events", {"date": d}), {}) or {}


@router.post("/events")
async def add_event(req: EventRequest, user: dict = Depends(get_current_user)):
    """手动新增事件(画像页;与对话确认卡同一落库口径)。"""
    args = {k: v for k, v in req.model_dump().items() if v is not None}
    args["idempotency_key"] = f"api-evt-{time.time_ns()}"
    res = await tools.call_tool("add_memory_event", args)
    if not isinstance(res, dict) or res.get("status") not in ("success", "duplicate"):
        raise HTTPException(status_code=400, detail=(res or {}).get("message", "事件写入失败"))
    return {"status": "ok", "result": tools.tool_data(res)}
