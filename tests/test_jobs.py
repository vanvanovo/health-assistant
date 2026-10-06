# tests/test_jobs.py
# 四类主动服务任务离线用例:幂等 / 触发前复检 / 48h 防重 / 报告降级。

from datetime import date, timedelta

import pytest

from backend.core import jobs, notify_store, reporter
from backend.core import scheduler as sched

TODAY = "2026-10-06"


def mock_tools(monkeypatch, handlers: dict | None = None):
    calls = []
    handlers = handlers or {}

    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        return handlers.get(name, {"status": "success", "data": {}})

    monkeypatch.setattr(jobs.tools, "call_tool", fake)
    return calls


def mock_store(monkeypatch, existing: set | None = None):
    state = {"existing": set(existing or set()), "added": [], "reports": []}

    async def message_exists(msg_key):
        return msg_key in state["existing"]

    async def add_message(type, title, body, msg_key, payload=None):
        if msg_key in state["existing"]:
            return None
        state["existing"].add(msg_key)
        state["added"].append({"type": type, "title": title, "body": body, "msg_key": msg_key, "payload": payload})
        return {"id": len(state["added"]), "msg_key": msg_key}

    async def save_report(type, ps, pe, content, data=None):
        state["reports"].append({"type": type, "period": (ps, pe), "content": content})
        return {"id": len(state["reports"])}

    monkeypatch.setattr(notify_store, "message_exists", message_exists)
    monkeypatch.setattr(notify_store, "add_message", add_message)
    monkeypatch.setattr(notify_store, "save_report", save_report)
    return state


PLAN_WITH_PENDING = {
    "status": "success",
    "data": {"week_start": "2026-10-05", "items": [
        {"id": 11, "date": TODAY, "kind": "workout", "title": "慢跑 5km", "status": "pending", "est_minutes": 40},
        {"id": 12, "date": TODAY, "kind": "habit", "title": "睡前拉伸", "status": "pending", "est_minutes": 10},
        {"id": 13, "date": TODAY, "kind": "habit", "title": "喝水", "status": "done", "est_minutes": 0},
    ]},
}


@pytest.mark.asyncio
async def test_remind_skipped_when_nothing_pending(monkeypatch):
    mock_tools(monkeypatch, {"get_active_plan": {"status": "success", "data": {"items": []}}})
    state = mock_store(monkeypatch)
    out = await jobs.job_checkin_remind(TODAY)
    assert out["status"] == "skipped"
    assert state["added"] == []


@pytest.mark.asyncio
async def test_remind_sent_then_duplicate(monkeypatch):
    mock_tools(monkeypatch, {"get_active_plan": PLAN_WITH_PENDING})
    state = mock_store(monkeypatch)
    first = await jobs.job_checkin_remind(TODAY)
    second = await jobs.job_checkin_remind(TODAY)
    assert first["status"] == "sent" and second["status"] == "duplicate"
    assert len(state["added"]) == 1
    assert state["added"][0]["msg_key"] == f"remind:{TODAY}"
    assert "2 项没打卡" in state["added"][0]["body"]
    assert "50 分钟" in state["added"][0]["body"]   # 40 + 10


@pytest.mark.asyncio
async def test_brief_saves_report_and_message(monkeypatch):
    mock_store(monkeypatch)

    async def fake_brief(day):
        return {"content": "今日简报内容", "facts": {"日期": day.isoformat()}}

    monkeypatch.setattr(jobs.reporter, "build_daily_brief", fake_brief)
    out = await jobs.job_daily_brief(TODAY)
    assert out["status"] == "sent" and out["report_id"] == 1
    state = None  # noqa
    replay = await jobs.job_daily_brief(TODAY)
    assert replay["status"] == "duplicate"


@pytest.mark.asyncio
async def test_weekly_report(monkeypatch):
    state = mock_store(monkeypatch)

    async def fake_weekly(ws):
        return {"content": "周报内容", "facts": {}}

    monkeypatch.setattr(jobs.reporter, "build_weekly_report", fake_weekly)
    out = await jobs.job_weekly_report(TODAY)          # 2026-10-06(周二)→ 当周周一 10-05
    assert out["status"] == "sent"
    assert state["reports"][0]["period"] == ("2026-10-05", "2026-10-11")


@pytest.mark.asyncio
async def test_alerts_none_on_clean_data(monkeypatch):
    clean = [
        {"date": TODAY, "sleep_hours": 7.5, "weight_kg": 68.0, "workout_type": "running", "workout_minutes": 30},
    ]
    mock_tools(monkeypatch, {
        "query_records": {"status": "success", "data": {"records": clean}},
        "get_range_summary": {"status": "success", "data": {"checkin": {"completion_rate": 0.8}}},
    })
    state = mock_store(monkeypatch)
    out = await jobs.job_alerts(TODAY)
    assert out["status"] == "none" and state["added"] == []


@pytest.mark.asyncio
async def test_alerts_sent_and_48h_dedupe(monkeypatch):
    low_sleep = [
        {"date": (date.fromisoformat(TODAY) - timedelta(days=1)).isoformat(), "sleep_hours": 5.5},
        {"date": TODAY, "sleep_hours": 5.6},
    ]
    mock_tools(monkeypatch, {
        "query_records": {"status": "success", "data": {"records": low_sleep}},
        "get_range_summary": {"status": "success", "data": {"checkin": {"completion_rate": 0.8}}},
    })
    mock_store(monkeypatch)
    first = await jobs.job_alerts(TODAY)
    assert first["status"] == "sent"
    assert any(a["rule"] == "sleep_debt" for a in first["alerts"])

    # 同一天复放 → 当日 key 已存在 → duplicate;昨天报过 → 48h 内跳过
    replay = await jobs.job_alerts(TODAY)
    assert replay["status"] == "none"
    yesterday_key = f"alert:sleep_debt:{(date.fromisoformat(TODAY) - timedelta(days=1)).isoformat()}"
    mock_store(monkeypatch, existing={yesterday_key})
    third = await jobs.job_alerts(TODAY)
    assert third["status"] == "none"


@pytest.mark.asyncio
async def test_reporter_fallback_when_llm_down(monkeypatch):
    async def fake_tool(name, arguments, timeout=None):
        return {"status": "success", "data": {}}

    monkeypatch.setattr(reporter.tools, "call_tool", fake_tool)

    async def boom(messages, **kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(reporter.llm_json, "chat_text", boom)
    out = await reporter.build_daily_brief(date.fromisoformat(TODAY))
    assert "早点休息" in out["content"]


def test_scheduler_time_parsers():
    assert sched._hm("20:15", 20, 0) == (20, 15)
    assert sched._hm("乱写的", 20, 0) == (20, 0)
    assert sched._weekly("周日 21:00") == ("sun", 21, 0)
    assert sched._weekly("周三 7:30") == ("wed", 7, 30)
    assert sched._weekly("09:00") == ("sun", 9, 0)      # 无星期 → 默认周日
