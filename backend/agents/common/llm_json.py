# backend/agents/common/llm_json.py
# LLM 文本/JSON 调用封装(节点统一入口;离线测试 monkeypatch 这一层即可)。

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.llm import get_llm_client

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_block(text: str) -> dict:
    """从 LLM 输出解析 JSON:先剥 ```json 代码块,再尝试整体 loads,
    最后兜底截取第一个 { 到最后一个 }。失败抛 ValueError。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("LLM 返回为空")
    cleaned = _FENCE_RE.sub("", raw).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        raise ValueError(f"JSON 顶层不是对象: {type(data).__name__}")
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}") from e
    raise ValueError("未找到合法 JSON 对象")


async def chat_text(messages: list[dict], **kw) -> str:
    """自由文本调用。"""
    return await get_llm_client().achat(messages, **kw)


async def chat_json(messages: list[dict], *, retries: int = 1, **kw) -> dict:
    """要求 LLM 输出 JSON:解析失败时追加约束重试,仍失败抛 ValueError。"""
    attempt_messages: list[dict] = list(messages)
    last_err: Exception | None = None
    for _ in range(retries + 1):
        text = await chat_text(attempt_messages, **kw)
        try:
            return parse_json_block(text)
        except ValueError as e:
            last_err = e
            attempt_messages = list(messages) + [
                {"role": "user", "content": "上次输出不是合法 JSON。请只输出严格 JSON,不要任何解释或代码块标记。"}
            ]
    raise ValueError(f"LLM 未返回合法 JSON: {last_err}")
