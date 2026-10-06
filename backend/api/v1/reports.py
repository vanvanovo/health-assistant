# backend/api/v1/reports.py
# 报告中心:简报 / 周报历史。

from fastapi import APIRouter, Depends, Query

from backend.core import notify_store
from backend.dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["报告"])


@router.get("")
async def list_reports(
    type: str | None = Query(None, pattern="^(daily|weekly)$"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    items = await notify_store.list_reports(type=type, limit=limit)
    return {"count": len(items), "reports": items}
