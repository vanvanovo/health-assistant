# backend/agents/common/tools.py
# MCP 工具调用封装(Agent 节点统一入口;离线测试 monkeypatch call_tool)。

from __future__ import annotations

from typing import Any

from backend.config import get_settings
from backend.mcp.client import call_mcp_tool


async def call_tool(name: str, arguments: dict, timeout: float | None = None) -> Any:
    """调用健康 MCP 工具(经网关的 HTTP 接口,与生产链路一致)。"""
    s = get_settings()
    return await call_mcp_tool(s.mcp_health_url, name, arguments, timeout)


def tool_data(res: Any, default: Any = None) -> Any:
    """从工具返回中取 data;非 success 时返回 default。"""
    if isinstance(res, dict) and res.get("status") == "success":
        return res.get("data", default)
    return default
