# backend/api/v1/chat.py
# 对话入口:POST /api/v1/chat/stream(SSE:routing / progress / card / token / meta / done)。

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core.orchestrator import run_chat
from backend.dependencies import get_current_user

router = APIRouter(prefix="/chat", tags=["对话"])


class ChatRequest(BaseModel):
    message: str


@router.post("/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)):
    async def gen():
        async for ev in run_chat(req.message):
            data = json.dumps(ev["data"], ensure_ascii=False, default=str)
            yield f"event: {ev['event']}\ndata: {data}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
