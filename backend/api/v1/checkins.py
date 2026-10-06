# backend/api/v1/checkins.py
# 表单打卡入口:与对话打卡同链路(都走 MCP upsert_checkin)。

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.agents.common import tools
from backend.core import cache
from backend.core.cache import LockBusy
from backend.dependencies import get_current_user

router = APIRouter(prefix="/checkins", tags=["打卡"])


class CheckinRequest(BaseModel):
    plan_item_id: int | None = None
    date: str | None = None
    kind: str = "habit"
    title: str | None = None
    status: str = "done"
    feeling_score: int | None = None
    note: str | None = None


@router.post("")
async def create_checkin(req: CheckinRequest, user: dict = Depends(get_current_user)):
    args = {k: v for k, v in req.model_dump().items() if v is not None}
    args["idempotency_key"] = f"api-{time.time_ns()}"

    # P10:同一计划项并发打卡 → 短锁串行化(拿不到锁返回 409;Redis 不可用降级放行)
    lock_name = f"lock:checkin:{req.plan_item_id}" if req.plan_item_id else None
    token = None
    if lock_name:
        try:
            token = await cache.acquire_lock(lock_name)
        except LockBusy:
            raise HTTPException(status_code=409, detail="这个打卡项正在处理另一笔请求,请稍后重试") from None
    try:
        res = await tools.call_tool("upsert_checkin", args)
    finally:
        if lock_name:
            await cache.release_lock(lock_name, token)

    if not isinstance(res, dict) or res.get("status") not in ("success", "duplicate"):
        detail = res.get("message") if isinstance(res, dict) else "打卡失败"
        raise HTTPException(status_code=400, detail=detail)
    return {"status": "ok", "result": res.get("data") or res}
