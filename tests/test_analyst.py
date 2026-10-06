# tests/test_analyst.py
# 分析图离线用例(全 mock):统计口径调用、异常规则、解读组装。

import pytest

from backend.agents.analyst.graph import run_analyst
from backend.agents.analyst.rules import detect_anomalies
from backend.agents.common import llm_json, tools

TODAY = "2026-10-06"

SUMMARY_OK = {
    "date_from": "2026-09-07", "date_to": "2026-10-06", "recorded_days": 30,
    "workout": {"days": 12, "total_minutes": 480, "by_type": {"running": 7, "strength": 5}},
    "weight": {"start": 69.5, "end": 69.0, "delta": -0.5, "min": 68.8, "max": 69.6, "avg": 69.2, "points": 30},
    "sleep": {"avg": 7.2, "min": 6.2, "max": 8.3, "nights": 30},
    "feeling": {"good": 15, "normal": 10, "tired": 5},
    "checkin": {"done": 10, "partial": 2, "missed": 2, "pending": 2, "elapsed": 14, "completion_rate": 0.79},
}


def mock_tools(monkeypatch, result):
    calls = []

    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        return result

    monkeypatch.setattr(tools, "call_tool", fake)
    return calls


def mock_llm_text(monkeypatch, text="整体状态不错,保持节奏。"):
    async def fake(messages, **kw):
        return text

    monkeypatch.setattr(llm_json, "chat_text", fake)


@pytest.mark.asyncio
async def test_normal_summary_ok(monkeypatch):
    calls = mock_tools(monkeypatch, {"status": "success", "data": SUMMARY_OK})
    mock_llm_text(monkeypatch, "近 30 天训练 12 次,体重稳中有降,睡眠达标。")
    r = await run_analyst(today=TODAY)
    assert r["status"] == "ok"
    assert r["card"]["type"] == "stats"
    assert r["card"]["payload"]["interpretation"]
    assert calls[0]["name"] == "get_range_summary"
    assert calls[0]["args"]["date_from"] == "2026-09-07"   # 默认近 30 天
    assert calls[0]["args"]["date_to"] == TODAY


@pytest.mark.asyncio
async def test_explicit_range_used(monkeypatch):
    calls = mock_tools(monkeypatch, {"status": "success", "data": SUMMARY_OK})
    mock_llm_text(monkeypatch)
    r = await run_analyst(date_from="2026-09-01", date_to="2026-09-30", today=TODAY)
    assert r["status"] == "ok"
    assert calls[0]["args"]["date_from"] == "2026-09-01"
    assert calls[0]["args"]["date_to"] == "2026-09-30"


@pytest.mark.asyncio
async def test_sleep_debt_rule(monkeypatch):
    s = {**SUMMARY_OK, "sleep": {"avg": 6.0, "min": 5.2, "max": 6.8, "nights": 20}}
    mock_tools(monkeypatch, {"status": "success", "data": s})
    mock_llm_text(monkeypatch, "睡眠偏少。")
    r = await run_analyst(today=TODAY)
    assert any(a["rule"] == "sleep_debt" for a in r["card"]["payload"]["anomalies"])
    assert "睡眠" in r["message"]


@pytest.mark.asyncio
async def test_fatigue_rule(monkeypatch):
    s = {**SUMMARY_OK, "feeling": {"good": 2, "normal": 3, "tired": 5}}
    mock_tools(monkeypatch, {"status": "success", "data": s})
    mock_llm_text(monkeypatch)
    r = await run_analyst(today=TODAY)
    assert any(a["rule"] == "fatigue" for a in r["card"]["payload"]["anomalies"])


def test_weight_change_rule():
    s = {**SUMMARY_OK, "recorded_days": 10,
         "weight": {"start": 70.0, "end": 68.0, "delta": -2.0, "min": 68.0, "max": 70.0, "avg": 69.0, "points": 10}}
    assert any(a["rule"] == "weight_change" for a in detect_anomalies(s))


def test_adherence_rule():
    s = {**SUMMARY_OK, "checkin": {"done": 2, "partial": 1, "missed": 7, "pending": 0, "elapsed": 10, "completion_rate": 0.25}}
    assert any(a["rule"] == "adherence" for a in detect_anomalies(s))


def test_ok_rule_when_stable():
    rules = [a["rule"] for a in detect_anomalies(SUMMARY_OK)]
    assert rules == ["ok"]


@pytest.mark.asyncio
async def test_tool_failure_raises(monkeypatch):
    mock_tools(monkeypatch, {"status": "invalid", "message": "日期非法"})
    mock_llm_text(monkeypatch)
    with pytest.raises(RuntimeError):
        await run_analyst(today=TODAY)
