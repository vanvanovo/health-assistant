# backend/core/reporter.py
# 简报 / 周报生成:规则算事实 + LLM 只组织;失败降级为模板文本(不阻塞主动服务)。

from __future__ import annotations

import json
from datetime import date, timedelta

from backend.agents.common import llm_json, tools

SYSTEM = """你是个人健康助手的「报告撰写」模块。
硬约束:
1. 只能引用给定事实中的数字与内容,禁止编造任何未给出的指标。
2. 不做医疗诊断,不开药;语言像朋友,简洁自然。
3. 简报 2~4 句;周报 4~6 句(亮点/不足/下周建议)。
4. 只输出正文文本,不要标题、不要 JSON、不要列表符号。"""


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def build_daily_brief(day: date) -> dict:
    day_s = day.isoformat()
    today_summary = tools.tool_data(
        await tools.call_tool("get_range_summary", {"date_from": day_s, "date_to": day_s}), {}
    ) or {}
    week_progress = tools.tool_data(
        await tools.call_tool("get_plan_progress", {"week_start": _monday(day).isoformat()}), {}
    ) or {}
    plan = tools.tool_data(await tools.call_tool("get_active_plan", {"date": day_s}), {}) or {}
    today_items = [it for it in (plan.get("items") or []) if it.get("date") == day_s]
    tomorrow = day + timedelta(days=1)
    plan2 = tools.tool_data(await tools.call_tool("get_active_plan", {"date": tomorrow.isoformat()}), {}) or {}
    tomorrow_items = [it for it in (plan2.get("items") or []) if it.get("date") == tomorrow.isoformat()]

    facts = {
        "日期": day_s,
        "今日记录": today_summary,
        "本周计划进度": week_progress.get("progress"),
        "今日计划项": [{"title": it.get("title"), "status": it.get("status")} for it in today_items],
        "明日计划项": [{"title": it.get("title"), "kind": it.get("kind")} for it in tomorrow_items],
    }
    text = await _compose(facts, fallback=_brief_fallback(facts))
    return {"content": text, "facts": facts}


async def build_weekly_report(week_start: date) -> dict:
    ws = _monday(week_start)
    we = ws + timedelta(days=6)
    summary = tools.tool_data(
        await tools.call_tool("get_range_summary", {"date_from": ws.isoformat(), "date_to": we.isoformat()}), {}
    ) or {}
    progress = tools.tool_data(
        await tools.call_tool("get_plan_progress", {"week_start": ws.isoformat()}), {}
    ) or {}
    meals = tools.tool_data(
        await tools.call_tool("get_meal_summary", {"date_from": ws.isoformat(), "date_to": we.isoformat()}), {}
    ) or {}
    facts = {
        "周起始": ws.isoformat(), "周结束": we.isoformat(),
        "本周记录": summary, "计划进度": progress.get("progress"), "饮食记录": meals,
    }
    text = await _compose(facts, fallback=_weekly_fallback(facts))
    return {"content": text, "facts": facts}


async def _compose(facts: dict, fallback: str) -> str:
    try:
        text = await llm_json.chat_text(
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": "给定事实:\n" + json.dumps(facts, ensure_ascii=False, default=str) + "\n\n请输出报告正文。",
                },
            ],
            temperature=0.3,
        )
        text = (text or "").strip()
        return text or fallback
    except Exception:  # noqa: BLE001
        return fallback


def _brief_fallback(facts: dict) -> str:
    items = facts.get("今日计划项") or []
    done = sum(1 for it in items if it.get("status") == "done")
    parts = [f"今日计划完成 {done}/{len(items)} 项。" if items else "今天没有安排计划项。"]
    tmr = facts.get("明日计划项") or []
    if tmr:
        parts.append("明日安排:" + "、".join(str(it.get("title")) for it in tmr[:3]) + "。")
    wt = ((facts.get("今日记录") or {}).get("workout") or {})
    if wt.get("total_minutes"):
        parts.append(f"今日训练 {wt['total_minutes']} 分钟。")
    parts.append("早点休息~")
    return "".join(parts)


def _weekly_fallback(facts: dict) -> str:
    s = facts.get("本周记录") or {}
    p = facts.get("计划进度") or {}
    w = s.get("workout") or {}
    parts = [f"本周训练 {w.get('days', 0)} 次、共 {w.get('total_minutes', 0)} 分钟。"]
    if p.get("completion_rate") is not None:
        parts.append(f"计划完成率 {int(p['completion_rate'] * 100)}%。")
    sl = s.get("sleep") or {}
    if sl.get("avg") is not None:
        parts.append(f"平均睡眠 {sl['avg']} 小时。")
    wt = s.get("weight") or {}
    if wt:
        sign = "+" if (wt.get("delta") or 0) > 0 else ""
        parts.append(f"体重 {wt.get('start')}→{wt.get('end')} kg({sign}{wt.get('delta')}kg)。")
    parts.append("下周继续加油~")
    return "".join(parts)
