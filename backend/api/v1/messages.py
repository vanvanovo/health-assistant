# backend/api/v1/messages.py
# 站内信:列表(含未读数)/ 标记已读。

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core import notify_store
from backend.dependencies import get_current_user

router = APIRouter(prefix="/messages", tags=["站内信"])


@router.get("")
async def list_messages(
    unread: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    items = await notify_store.list_messages(unread_only=unread, limit=limit)
    return {"count": len(items), "unread": await notify_store.count_unread(), "messages": items}


class ReadRequest(BaseModel):
    id: int | None = None
    all: bool = False


@router.post("/read")
async def mark_read(req: ReadRequest, user: dict = Depends(get_current_user)):
    if not req.all and req.id is None:
        return {"updated": 0, "unread": await notify_store.count_unread()}
    updated = await notify_store.mark_read(req.id, all_=req.all)
    return {"updated": updated, "unread": await notify_store.count_unread()}
