# backend/agents/recorder/nodes.py
# 记录图节点:parse(LLM 抽取)→ validate(规则校验)→ clarify / upsert(MCP)→ confirm。

from __future__ import annotations

from datetime import date

from backend.agents.common import llm_json, tools
from backend.agents.common.result import agent_result
from backend.agents.common.utils import short_hash

from . import prompts

WORKOUT_TYPES = {"running", "strength", "rest", "other"}
FEELINGS = {"good", "normal", "tired"}

TYPE_CN = {"running": "跑步", "strength": "力量训练", "rest": "休息", "other": "运动"}
FEEL_CN = {"good": "不错", "normal": "一般", "tired": "疲惫"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _record_summary(cleaned: dict) -> str:
    """把已抽取字段拼成一句人话(追问/确认复用)。"""
    parts = []
    if cleaned.get("workout_minutes"):
        parts.append(f"{TYPE_CN.get(cleaned.get('workout_type'), '运动')} {int(cleaned['workout_minutes'])} 分钟")
    elif cleaned.get("workout_type") == "rest":
        parts.append("休息日")
    if cleaned.get("weight_kg") is not None:
        parts.append(f"体重 {cleaned['weight_kg']} kg")
    if cleaned.get("sleep_hours") is not None:
        parts.append(f"睡眠 {cleaned['sleep_hours']} 小时")
    if cleaned.get("feeling"):
        parts.append(f"体感{FEEL_CN.get(cleaned['feeling'], cleaned['feeling'])}")
    return "、".join(parts)


async def parse_node(state) -> dict:
    data = await llm_json.chat_json(
        [
            {"role": "system", "content": prompts.build_system(state["today"])},
            {"role": "user", "content": state["user_input"]},
        ],
        temperature=0,
    )
    return {"extracted": data if isinstance(data, dict) else {}}


async def validate_node(state) -> dict:
    raw = state.get("extracted") or {}
    today = date.fromisoformat(state["today"])
    errors: list[str] = []
    cleaned: dict = {}

    # 日期:缺省今天;不允许未来
    d = None
    if isinstance(raw.get("date"), str):
        try:
            d = date.fromisoformat(raw["date"].strip()[:10])
        except ValueError:
            d = None
    if d is None:
        d = today
    if d > today:
        errors.append(f"日期 {d.isoformat()} 晚于今天")
        d = today
    cleaned["date"] = d.isoformat()

    # 数值范围校验(与 MCP 工具同口径,双保险)
    weight = _num(raw.get("weight_kg"))
    if weight is not None and not (30 <= weight <= 300):
        errors.append(f"体重 {weight}kg 不在合理范围(30~300)")
        weight = None
    sleep = _num(raw.get("sleep_hours"))
    if sleep is not None and not (0 <= sleep <= 24):
        errors.append(f"睡眠 {sleep} 小时不在合理范围(0~24)")
        sleep = None
    minutes = _num(raw.get("workout_minutes"))
    if minutes is not None and not (0 <= minutes <= 600):
        errors.append(f"训练时长 {minutes} 分钟不在合理范围(0~600)")
        minutes = None

    wtype = raw.get("workout_type") if raw.get("workout_type") in WORKOUT_TYPES else None
    feeling = raw.get("feeling") if raw.get("feeling") in FEELINGS else None
    note = raw.get("note") if isinstance(raw.get("note"), str) and raw.get("note").strip() else None

    cleaned.update(
        workout_type=wtype, workout_minutes=int(minutes) if minutes is not None else None,
        weight_kg=weight, sleep_hours=sleep, feeling=feeling, note=note,
    )

    has_other = bool((minutes or 0) > 0 or wtype is not None or sleep is not None or feeling is not None or note)
    nothing = weight is None and not has_other
    need_clarify = bool(errors) or nothing or (weight is None and has_other)
    return {
        "cleaned": cleaned,
        "errors": errors,
        "need_clarify": need_clarify,
        "next_step": "clarify" if need_clarify else "upsert",
    }


async def clarify_node(state) -> dict:
    errors = state.get("errors") or []
    cleaned = state.get("cleaned") or {}
    if errors:
        message = "这句里有些数字不太对:" + "、".join(errors) + "。麻烦再确认一下?"
    elif not _record_summary(cleaned):
        message = prompts.CLARIFY_NOTHING
    else:
        message = prompts.clarify_weight(_record_summary(cleaned))
    return {
        "result": agent_result(
            "recorder", "clarify", message,
            data={"extracted": cleaned, "errors": errors},
        )
    }


async def upsert_node(state) -> dict:
    cleaned = state["cleaned"]
    fields = {
        k: cleaned[k]
        for k in ("workout_type", "workout_minutes", "weight_kg", "sleep_hours", "feeling", "note")
        if cleaned.get(k) is not None
    }
    key = f"rec-{cleaned['date']}-{short_hash(state['user_input'])}"
    res = await tools.call_tool(
        "upsert_health_record", {"date": cleaned["date"], **fields, "idempotency_key": key}
    )
    return {"upsert_res": res if isinstance(res, dict) else {}}


async def confirm_node(state) -> dict:
    res = state.get("upsert_res") or {}
    if res.get("status") not in ("success", "duplicate"):
        return {
            "result": agent_result(
                "recorder", "failed",
                f"记录写入失败:{res.get('message', '未知错误')}",
                degraded=True,
            )
        }
    record = ((res.get("data") or {}).get("record")) or {}
    summary = _record_summary(record) or "已记录"
    message = f"已记录 {record.get('date', '')}:{summary}。"
    card = {"type": "record_confirm", "payload": {"record": record, "mode": res.get("status")}}
    return {
        "result": agent_result("recorder", "ok", message, card=card, data={"record": record})
    }
