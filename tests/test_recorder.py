# tests/test_recorder.py
# 记录图离线用例(全 mock:不联网、不连库)。

import pytest

from backend.agents.common import llm_json, tools
from backend.agents.recorder.graph import run_recorder

TODAY = "2026-10-06"


def mock_llm(monkeypatch, extracted):
    async def fake(messages, **kw):
        return extracted

    monkeypatch.setattr(llm_json, "chat_json", fake)


def mock_tool(monkeypatch, result):
    calls = []

    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        return result

    monkeypatch.setattr(tools, "call_tool", fake)
    return calls


FULL_EXTRACT = {
    "date": "2026-10-06", "workout_type": "running", "workout_minutes": 30,
    "weight_kg": 68.0, "sleep_hours": 7.0, "feeling": "good", "note": None,
}
FULL_RECORD = {
    "id": 1, "date": "2026-10-06", "workout_type": "running", "workout_minutes": 30,
    "weight_kg": 68.0, "sleep_hours": 7.0, "feeling": "good", "note": None, "source": "llm",
}


@pytest.mark.asyncio
async def test_full_record_ok(monkeypatch):
    mock_llm(monkeypatch, FULL_EXTRACT)
    calls = mock_tool(monkeypatch, {"status": "success", "data": {"created": True, "updated": False, "record": FULL_RECORD}})
    r = await run_recorder("今天慢跑30分钟,体重68,睡了7小时,感觉不错", today=TODAY)
    assert r["status"] == "ok"
    assert r["card"]["type"] == "record_confirm"
    assert calls[0]["name"] == "upsert_health_record"
    assert calls[0]["args"]["date"] == TODAY
    assert calls[0]["args"]["weight_kg"] == 68.0
    assert calls[0]["args"]["idempotency_key"]


@pytest.mark.asyncio
async def test_missing_weight_clarifies(monkeypatch):
    mock_llm(monkeypatch, {"date": "2026-10-06", "workout_type": "running", "workout_minutes": 30})
    calls = mock_tool(monkeypatch, {"status": "success", "data": {}})
    r = await run_recorder("今天跑了5公里", today=TODAY)
    assert r["status"] == "clarify"
    assert "体重" in r["message"]
    assert calls == []          # 追问时不写库


@pytest.mark.asyncio
async def test_nothing_extracted_clarifies(monkeypatch):
    mock_llm(monkeypatch, {})
    calls = mock_tool(monkeypatch, {"status": "success", "data": {}})
    r = await run_recorder("你好呀", today=TODAY)
    assert r["status"] == "clarify"
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_weight_blocked(monkeypatch):
    mock_llm(monkeypatch, {"date": "2026-10-06", "weight_kg": 999, "sleep_hours": 7})
    calls = mock_tool(monkeypatch, {"status": "success", "data": {}})
    r = await run_recorder("体重999", today=TODAY)
    assert r["status"] == "clarify"
    assert "体重" in r["message"]
    assert calls == []


@pytest.mark.asyncio
async def test_missing_date_defaults_today(monkeypatch):
    mock_llm(monkeypatch, {"weight_kg": 68.0})
    calls = mock_tool(monkeypatch, {"status": "success", "data": {"record": FULL_RECORD, "created": True}})
    r = await run_recorder("体重68", today=TODAY)
    assert r["status"] == "ok"
    assert calls[0]["args"]["date"] == TODAY


@pytest.mark.asyncio
async def test_future_date_blocked(monkeypatch):
    mock_llm(monkeypatch, {"date": "2026-12-01", "weight_kg": 68.0})
    calls = mock_tool(monkeypatch, {"status": "success", "data": {}})
    r = await run_recorder("体重68", today=TODAY)
    assert r["status"] == "clarify"
    assert "日期" in r["message"]
    assert calls == []


@pytest.mark.asyncio
async def test_idempotent_replay_still_ok(monkeypatch):
    mock_llm(monkeypatch, FULL_EXTRACT)
    mock_tool(monkeypatch, {"status": "duplicate", "data": {"record": FULL_RECORD}})
    r = await run_recorder("今天慢跑30分钟,体重68,睡了7小时", today=TODAY)
    assert r["status"] == "ok"
    assert r["card"]["payload"]["mode"] == "duplicate"


@pytest.mark.asyncio
async def test_tool_failure_degrades(monkeypatch):
    mock_llm(monkeypatch, FULL_EXTRACT)
    mock_tool(monkeypatch, {"status": "invalid", "message": "参数不合法"})
    r = await run_recorder("今天慢跑30分钟,体重68", today=TODAY)
    assert r["status"] == "failed"
    assert r["degraded"] is True
