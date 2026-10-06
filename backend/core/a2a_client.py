# backend/core/a2a_client.py
# A2A 客户端:调用独立的知识库 RAG Agent(P9)。
# - 统一超时(15s,与 cs-platform 实测口径一致);失败抛 A2ACallError,由调用方降级
# - 解析 Task 状态:completed → 读 artifacts;其余 → 抛错
# - artifacts 契约:{answer, sources[], answer_mode, need_clarify, clarify, safety}

from __future__ import annotations

import asyncio
import json
import uuid

from python_a2a import A2AClient, Message, MessageRole, Task, TextContent

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class A2ACallError(Exception):
    """A2A 调用失败(超时 / 连接失败 / 任务非完成态)。"""


async def call_health_rag(query: str) -> dict:
    """调用健康知识 RAG Agent;失败抛 A2ACallError。"""
    settings = get_settings()
    client = A2AClient(settings.rag_agent_url)
    message = Message(content=TextContent(text=query), role=MessageRole.USER)
    task = Task(id=f"task-{uuid.uuid4().hex[:10]}", message=message.to_dict())

    try:
        raw = await asyncio.wait_for(
            client.send_task_async(task),
            timeout=settings.a2a_timeout_seconds,
        )
    except asyncio.TimeoutError as e:
        raise A2ACallError(f"RAG Agent 超时(>{settings.a2a_timeout_seconds}s)") from e
    except Exception as e:  # noqa: BLE001
        raise A2ACallError(f"RAG Agent 调用失败:{e}") from e

    state = getattr(getattr(raw, "status", None), "state", None)
    state_val = getattr(state, "value", state)
    if state_val != "completed":
        msg = getattr(getattr(raw, "status", None), "message", None)
        raise A2ACallError(
            f"RAG Agent 任务未完成(state={state_val}):{json.dumps(msg, ensure_ascii=False, default=str)[:200]}"
        )
    try:
        text = raw.artifacts[0]["parts"][0]["text"]
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        raise A2ACallError(f"RAG Agent 返回解析失败:{e}") from e
