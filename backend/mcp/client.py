# backend/mcp/client.py
# MCP 客户端封装:调用 stateless MCP Server 的工具(JSON-RPC over HTTP,带 X-MCP-Key)。
# 服务间调用专用;stateless_http=True 每次 POST 自包含,无需 initialize 握手。

import json
from typing import Any

import httpx

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


def _headers() -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = get_settings().mcp_shared_key
    if key:
        headers["X-MCP-Key"] = key
    return headers


async def call_mcp_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float | None = None,
) -> Any:
    """调用 MCP 工具,返回反序列化后的对象(我们的工具统一返回单个 JSON 对象)。

    server_url 传挂载前缀,如 "http://localhost:8020/mcp/health";请求发往 {server_url}/mcp。
    """
    s = get_settings()
    timeout = timeout if timeout is not None else float(s.mcp_timeout_seconds)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    # trust_env=False:本地服务间调用永远不走系统代理
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.post(f"{server_url.rstrip('/')}/mcp", json=payload, headers=_headers())
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        raise ValueError(f"MCP tool '{tool_name}' error: {data['error'].get('message', str(data['error']))}")

    result = data.get("result", {}) or {}
    if result.get("isError"):
        err_text = ""
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("text"):
                err_text = item["text"]
                break
        raise ValueError(f"MCP tool '{tool_name}' failed: {err_text[:500]}")

    content = result.get("content", [])
    if not content:
        return None
    text = content[0].get("text", "")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


async def list_mcp_tools(server_url: str, timeout: float = 10.0) -> list[dict]:
    """列出 MCP Server 的工具清单(name / description / inputSchema)。"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.post(f"{server_url.rstrip('/')}/mcp", json=payload, headers=_headers())
        resp.raise_for_status()
    return resp.json().get("result", {}).get("tools", [])
