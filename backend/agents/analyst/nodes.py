# backend/agents/analyst/nodes.py
# 分析图节点:collect(MCP 统计)→ anomaly(规则)→ interpret(LLM 只解读)→ format(卡片)。

from __future__ import annotations

from datetime import date, timedelta

from backend.agents.common import llm_json, tools
from backend.agents.common.result import agent_result

from . import prompts
from .rules import detect_anomalies

DEFAULT_RANGE_DAYS = 30


async def collect_node(state) -> dict:
    today = date.fromisoformat(state["today"])
    date_from = state.get("date_from") or (today - timedelta(days=DEFAULT_RANGE_DAYS - 1)).isoformat()
    date_to = state.get("date_to") or today.isoformat()
    res = await tools.call_tool("get_range_summary", {"date_from": date_from, "date_to": date_to})
    summary = tools.tool_data(res)
    if not summary:
        raise RuntimeError(f"统计失败:{res.get('message') if isinstance(res, dict) else res}")
    return {"date_from": date_from, "date_to": date_to, "summary": summary}


async def anomaly_node(state) -> dict:
    return {"anomalies": detect_anomalies(state["summary"])}


async def interpret_node(state) -> dict:
    text = await llm_json.chat_text(
        [
            {"role": "system", "content": prompts.SYSTEM},
            {"role": "user", "content": prompts.build_user_message(state["summary"], state.get("anomalies") or [])},
        ],
        temperature=0.3,
    )
    return {"interpretation": text.strip()}


async def format_node(state) -> dict:
    summary = state["summary"]
    anomalies = state.get("anomalies") or []
    interpretation = state.get("interpretation") or ""

    warns = [a for a in anomalies if a.get("level") == "warn"]
    message = interpretation or "统计已完成。"
    if warns:
        message = message + " 提醒:" + "、".join(a["message"] for a in warns)

    card = {
        "type": "stats",
        "payload": {
            "date_from": state["date_from"],
            "date_to": state["date_to"],
            "summary": summary,
            "anomalies": anomalies,
            "interpretation": interpretation,
        },
    }
    return {
        "result": agent_result("analyst", "ok", message, card=card, data={"summary": summary})
    }
