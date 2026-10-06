# backend/agents/planner/nodes.py
# 计划图节点:context(MCP 聚合)→ adjust(规则)→ generate(LLM)→ save(MCP 版本化)→ format。

from __future__ import annotations

from datetime import date, timedelta

from backend.agents.common import llm_json, tools
from backend.agents.common.result import agent_result
from backend.agents.common.utils import short_hash
from backend.core import cache

from . import prompts
from .rules import compute_constraints, target_week_start, validate_plan_items

CONTEXT_DAYS = 30


async def context_node(state) -> dict:
    today = date.fromisoformat(state["today"])
    week_start = (
        date.fromisoformat(state["week_start"]) if state.get("week_start") else target_week_start(today)
    )
    date_from = (today - timedelta(days=CONTEXT_DAYS - 1)).isoformat()

    summary = tools.tool_data(await tools.call_tool("get_range_summary", {"date_from": date_from, "date_to": today.isoformat()}), {})
    profile = tools.tool_data(await tools.call_tool("get_profile", {}), {})
    events_res = await tools.call_tool("list_active_events", {"date": today.isoformat()})
    events = tools.tool_data(events_res, {}).get("events", []) if isinstance(tools.tool_data(events_res, {}), dict) else []
    history_plans = (tools.tool_data(await tools.call_tool("list_plans", {"weeks": 4}), {}) or {}).get("plans") or []
    cur_plan = tools.tool_data(await tools.call_tool("get_active_plan", {"date": today.isoformat()}), {}) or {}
    recent_items = cur_plan.get("items") or []

    return {
        "week_start": week_start.isoformat(),
        "summary": summary or {},
        "profile": profile or {},
        "events": events or [],
        "history_plans": history_plans,
        "recent_items": recent_items,
    }


async def adjust_node(state) -> dict:
    constraints = compute_constraints(
        state.get("summary") or {},
        state.get("profile") or {},
        state.get("events") or [],
        date.fromisoformat(state["week_start"]),
        recent_items=state.get("recent_items") or [],
        history_plans=state.get("history_plans") or [],
    )
    return {"constraints": constraints}


async def generate_node(state) -> dict:
    week_start = date.fromisoformat(state["week_start"])
    system = prompts.build_system(
        week_start, state["constraints"], state.get("summary") or {},
        state.get("profile") or {}, state.get("events") or [],
    )
    data = await llm_json.chat_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": state.get("user_input") or "请生成本周的周计划。"},
        ],
        temperature=0.3,
    )
    items = validate_plan_items(data.get("items"), week_start)   # 不合法 → ValueError
    plan = {
        "summary": str(data.get("summary") or "")[:200],
        "rationale": str(data.get("rationale") or "")[:300],
        "items": items,
    }
    return {"llm_plan": plan}


async def save_node(state) -> dict:
    plan = state["llm_plan"]
    key = f"planner:{state['week_start']}:{short_hash((state.get('user_input') or '') + state['constraints']['level'])}"
    # P10:同周并发保存 → 短锁串行化(Redis 不可用降级放行)
    lock_name = f"lock:plan:{state['week_start']}"
    try:
        lock_token = await cache.acquire_lock(lock_name)
    except cache.LockBusy:
        return {"saved": {"status": "busy", "message": "另一笔计划保存正在进行,请稍后重试"}}
    try:
        res = await tools.call_tool(
            "save_plan",
            {
                "week_start": state["week_start"],
                "items": plan["items"],
                "summary": plan["summary"],
                "rationale": plan["rationale"],
                "idempotency_key": key,
            },
        )
    finally:
        await cache.release_lock(lock_name, lock_token)
    return {"saved": res if isinstance(res, dict) else {}}


async def format_node(state) -> dict:
    saved = state.get("saved") or {}
    plan = state.get("llm_plan") or {}
    if saved.get("status") not in ("success", "duplicate"):
        return {
            "result": agent_result(
                "planner", "failed",
                f"计划保存失败:{saved.get('message', '未知错误')}",
                degraded=True,
            )
        }
    if saved.get("status") == "duplicate":
        plan_id, version = saved.get("plan_id"), saved.get("version")
    else:
        plan_id, version = (saved.get("data") or {}).get("plan_id"), (saved.get("data") or {}).get("version")

    message = (
        f"已生成 {state['week_start']} 起的周计划(v{version}):{plan.get('summary', '')}。"
        f"调档依据:{plan.get('rationale', '')}"
    )
    card = {
        "type": "plan",
        "payload": {
            "plan_id": plan_id,
            "version": version,
            "week_start": state["week_start"],
            "summary": plan.get("summary", ""),
            "rationale": plan.get("rationale", ""),
            "level": state["constraints"]["level"],
            "evidence": state["constraints"].get("evidence"),
            "items": plan.get("items", []),
        },
    }
    return {
        "result": agent_result(
            "planner", "ok", message, card=card,
            data={"plan_id": plan_id, "version": version, "level": state["constraints"]["level"]},
        )
    }
