# tests/test_planner.py
# 计划图离线用例(全 mock):调档规则、事件约束、LLM 输出校验、版本化保存。

import pytest

from backend.agents.common import llm_json, tools
from backend.agents.planner.graph import run_planner
from backend.agents.planner.rules import compute_constraints, validate_plan_items, target_week_start

from datetime import date

TODAY = "2026-10-06"                 # 周二
NEXT_MONDAY = "2026-10-12"

PROFILE = {"goal": "减脂", "equipment": ["哑铃", "跑鞋"], "schedule_pref": {"workout_days": [0, 2, 4, 6]}}

SUMMARY_UP = {
    "recorded_days": 30, "workout": {"days": 14, "total_minutes": 560, "by_type": {"running": 8, "strength": 6}},
    "weight": {"start": 69.5, "end": 69.0, "delta": -0.5, "min": 68.8, "max": 69.6, "avg": 69.2, "points": 30},
    "sleep": {"avg": 7.4, "min": 6.5, "max": 8.3, "nights": 30},
    "feeling": {"good": 20, "normal": 8, "tired": 2},
    "checkin": {"done": 16, "partial": 2, "missed": 2, "pending": 0, "elapsed": 20, "completion_rate": 0.85},
}
SUMMARY_DOWN = {
    **SUMMARY_UP,
    "feeling": {"good": 2, "normal": 3, "tired": 5},
    "checkin": {"done": 4, "partial": 2, "missed": 12, "pending": 0, "elapsed": 18, "completion_rate": 0.28},
}

PLAN_ITEMS = [
    {"date": "2026-10-12", "kind": "workout", "title": "慢跑 5km 轻松跑", "detail": "配速 6:30", "est_minutes": 40, "intensity": 1},
    {"date": "2026-10-14", "kind": "workout", "title": "力量:上肢推拉", "detail": "4 组", "est_minutes": 45, "intensity": 2},
    {"date": "2026-10-16", "kind": "workout", "title": "核心 + 拉伸", "detail": "", "est_minutes": 30, "intensity": 1},
    {"date": "2026-10-13", "kind": "habit", "title": "睡前拉伸 10 分钟", "detail": "", "est_minutes": 10, "intensity": 1},
]
LLM_PLAN = {"summary": "本周 3 练 + 拉伸", "rationale": "完成率 85%,保持节奏", "items": PLAN_ITEMS}


def mock_tools(monkeypatch, summary=SUMMARY_UP, profile=PROFILE, events=None, save=None):
    calls = []

    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        if name == "get_range_summary":
            return {"status": "success", "data": summary}
        if name == "get_profile":
            return {"status": "success", "data": profile}
        if name == "list_active_events":
            return {"status": "success", "data": {"events": events or []}}
        if name == "save_plan":
            return save or {"status": "success", "data": {"plan_id": 7, "version": 1, "week_start": NEXT_MONDAY, "item_count": len(arguments.get("items", []))}}
        return {"status": "success", "data": {}}

    monkeypatch.setattr(tools, "call_tool", fake)
    return calls


def mock_llm(monkeypatch, result, capture=None):
    async def fake(messages, **kw):
        if capture is not None:
            capture.append(messages)
        return result

    monkeypatch.setattr(llm_json, "chat_json", fake)


def save_call(calls):
    return next(c for c in calls if c["name"] == "save_plan") if any(c["name"] == "save_plan" for c in calls) else None


@pytest.mark.asyncio
async def test_default_week_is_next_monday(monkeypatch):
    calls = mock_tools(monkeypatch)
    mock_llm(monkeypatch, LLM_PLAN)
    r = await run_planner("帮我排下周计划", today=TODAY)
    assert r["status"] == "ok"
    assert r["card"]["payload"]["week_start"] == NEXT_MONDAY
    sc = save_call(calls)
    assert sc and sc["args"]["week_start"] == NEXT_MONDAY
    assert sc["args"]["idempotency_key"]
    assert r["data"]["version"] == 1


@pytest.mark.asyncio
async def test_level_down_when_low_rate(monkeypatch):
    calls = mock_tools(monkeypatch, summary=SUMMARY_DOWN)
    capture = []
    mock_llm(monkeypatch, LLM_PLAN, capture=capture)
    r = await run_planner(today=TODAY)
    assert r["status"] == "ok"
    assert r["card"]["payload"]["level"] == "down"
    prompt = "\n".join(m["content"] for m in capture[0])
    assert "降低强度" in prompt


@pytest.mark.asyncio
async def test_travel_event_marks_light_dates(monkeypatch):
    events = [{"id": 1, "kind": "travel", "description": "上海出差", "start_date": "2026-10-12", "end_date": "2026-10-14"}]
    calls = mock_tools(monkeypatch, events=events)
    capture = []
    mock_llm(monkeypatch, LLM_PLAN, capture=capture)
    r = await run_planner(today=TODAY)
    assert r["status"] == "ok"
    prompt = "\n".join(m["content"] for m in capture[0])
    assert "上海出差" in prompt and "轻量" in prompt
    assert "[4, 6]" in prompt          # 周一/周三是出差日,被移出训练日


@pytest.mark.asyncio
async def test_invalid_plan_item_raises_and_not_saved(monkeypatch):
    bad = {"summary": "x", "rationale": "y", "items": [{"date": "2026-10-12", "kind": "party", "title": "玩"}]}
    calls = mock_tools(monkeypatch)
    mock_llm(monkeypatch, bad)
    with pytest.raises(ValueError):
        await run_planner(today=TODAY)
    assert save_call(calls) is None


@pytest.mark.asyncio
async def test_item_out_of_week_raises(monkeypatch):
    bad = {"summary": "x", "rationale": "y", "items": [{"date": "2026-10-20", "kind": "workout", "title": "跑", "est_minutes": 30, "intensity": 1}]}
    mock_tools(monkeypatch)
    mock_llm(monkeypatch, bad)
    with pytest.raises(ValueError):
        await run_planner(today=TODAY)


@pytest.mark.asyncio
async def test_save_duplicate_still_ok(monkeypatch):
    calls = mock_tools(monkeypatch, save={"status": "duplicate", "plan_id": 7, "version": 2})
    mock_llm(monkeypatch, LLM_PLAN)
    r = await run_planner(today=TODAY)
    assert r["status"] == "ok"
    assert r["data"]["plan_id"] == 7 and r["data"]["version"] == 2


def test_target_week_start_rule():
    assert target_week_start(date(2026, 10, 6)).isoformat() == NEXT_MONDAY   # 周二 → 下周一
    assert target_week_start(date(2026, 10, 12)).isoformat() == "2026-10-19"  # 周一 → 下周一


def test_validate_plan_items_boundaries():
    ws = date(2026, 10, 12)
    ok = validate_plan_items([{"date": "2026-10-12", "kind": "habit", "title": "拉伸"}], ws)
    assert ok[0]["title"] == "拉伸"
    with pytest.raises(ValueError):
        validate_plan_items([], ws)
    with pytest.raises(ValueError):
        validate_plan_items([{"date": "2026-10-12", "kind": "workout", "title": "x", "intensity": 9}], ws)


def test_recovery_days_on_consecutive_low_feelings():
    recent = [
        {"date": "2026-10-03", "status": "done", "feeling_score": 2},
        {"date": "2026-10-04", "status": "done", "feeling_score": 2},
        {"date": "2026-10-05", "status": "partial", "feeling_score": 4},
    ]
    c = compute_constraints(SUMMARY_UP, PROFILE, [], date(2026, 10, 12), recent_items=recent, history_plans=[])
    assert c["recovery_days"] == 1
    assert any("恢复日" in r for r in c["reasons"])
    assert c["evidence"]["low_feeling_streak"] == 2


def test_swap_suggestion_after_four_weeks():
    history = [
        {"week_start": "2026-10-12", "titles": ["慢跑 5km 轻松跑"]},
        {"week_start": "2026-10-05", "titles": ["慢跑 5km 轻松跑", "核心 + 拉伸"]},
        {"week_start": "2026-09-28", "titles": ["慢跑 5km 轻松跑"]},
        {"week_start": "2026-09-21", "titles": ["慢跑 5km 轻松跑", "力量:上肢推拉"]},
    ]
    c = compute_constraints(SUMMARY_UP, PROFILE, [], date(2026, 10, 12), history_plans=history)
    assert any("慢跑 5km 轻松跑" in s for s in c["swap_suggestions"])
    assert any("换项" in r for r in c["reasons"])


def test_no_swap_when_streak_broken():
    history = [
        {"week_start": "2026-10-12", "titles": ["慢跑 5km 轻松跑"]},
        {"week_start": "2026-10-05", "titles": ["慢跑 5km 轻松跑"]},
        {"week_start": "2026-09-28", "titles": ["游泳 45 分钟"]},
        {"week_start": "2026-09-21", "titles": ["慢跑 5km 轻松跑"]},
    ]
    c = compute_constraints(SUMMARY_UP, PROFILE, [], date(2026, 10, 12), history_plans=history)
    assert c["swap_suggestions"] == []
