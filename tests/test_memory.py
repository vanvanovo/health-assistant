# tests/test_memory.py
# 长期记忆离线用例:抽取校验 / 签名 token / 确认写入(追加去重、事件幂等)。

import pytest

from backend.agents.common import llm_json, tools
from backend.agents.memory.handler import (
    apply_memory_token,
    decode_memory_token,
    encode_memory_token,
    run_memory,
)

TODAY = "2026-10-06"


def mock_llm(monkeypatch, result):
    async def fake(messages, **kw):
        return result

    monkeypatch.setattr(llm_json, "chat_json", fake)


def mock_tools(monkeypatch, handlers=None):
    calls = []
    handlers = handlers or {}

    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        return handlers.get(name, {"status": "success", "data": {}})

    monkeypatch.setattr(tools, "call_tool", fake)
    return calls


@pytest.mark.asyncio
async def test_profile_patch_returns_pending_card(monkeypatch):
    mock_llm(monkeypatch, {
        "action": "profile_patch",
        "patch": {"injuries": ["右膝不适"], "goal": "增肌"},
        "summary": "记录膝盖情况与目标",
    })
    r = await run_memory("我膝盖不好,目标是增肌", today=TODAY)
    assert r["status"] == "ok" and r["card"]["type"] == "profile_update"
    payload = r["card"]["payload"]
    assert payload["status"] == "pending"
    assert payload["append_fields"] == ["injuries"]
    claims = decode_memory_token(payload["token"])
    assert claims["payload"]["patch"]["injuries"] == ["右膝不适"]


@pytest.mark.asyncio
async def test_event_returns_pending_card(monkeypatch):
    mock_llm(monkeypatch, {
        "action": "event",
        "event": {"kind": "travel", "description": "上海出差", "start_date": "2026-10-12", "end_date": "2026-10-14"},
        "summary": "出差",
    })
    r = await run_memory("下周一到周三出差", today=TODAY)
    assert r["card"]["payload"]["event"]["kind"] == "travel"
    assert "确认写入" in r["message"]


@pytest.mark.asyncio
async def test_invalid_patch_rejected(monkeypatch):
    mock_llm(monkeypatch, {"action": "profile_patch", "patch": {"weight": "很重"}, "summary": "x"})
    r = await run_memory("x", today=TODAY)
    assert r["card"] is None and "没法自动写入" in r["message"]


@pytest.mark.asyncio
async def test_none_action(monkeypatch):
    mock_llm(monkeypatch, {"action": "none", "reason": "普通交流"})
    r = await run_memory("今天天气不错", today=TODAY)
    assert r["card"] is None and "普通交流" in r["message"]


def test_token_roundtrip():
    token = encode_memory_token({"type": "event", "event": {"kind": "checkup"}, "summary": "s"})
    claims = decode_memory_token(token)
    assert claims["typ"] == "memory" and claims["payload"]["type"] == "event"


def test_token_tamper_rejected():
    token = encode_memory_token({"type": "event", "event": {"kind": "checkup"}})
    with pytest.raises(ValueError):
        decode_memory_token(token[:-4] + "abcd")


def test_token_expired_rejected():
    token = encode_memory_token({"type": "event"}, ttl_minutes=-1)
    with pytest.raises(ValueError):
        decode_memory_token(token)


@pytest.mark.asyncio
async def test_apply_profile_patch_appends_and_dedupes(monkeypatch):
    token = encode_memory_token({
        "type": "profile_patch", "patch": {"injuries": ["右膝不适"]},
        "append_fields": ["injuries"], "summary": "s",
    })
    calls = mock_tools(monkeypatch, {
        "get_profile": {"status": "success", "data": {"injuries": ["右膝不适", "腰肌劳损"]}},
        "update_profile": {"status": "success", "data": {"injuries": ["右膝不适", "腰肌劳损"]}},
    })
    out = await apply_memory_token(token)
    assert out["status"] == "applied"
    upd = next(c for c in calls if c["name"] == "update_profile")
    assert upd["args"]["patch"]["injuries"] == ["右膝不适", "腰肌劳损"]   # 追加且去重
    assert upd["args"]["idempotency_key"]


@pytest.mark.asyncio
async def test_apply_event_duplicate_is_ok(monkeypatch):
    token = encode_memory_token({
        "type": "event", "event": {"kind": "travel", "description": "x", "start_date": TODAY, "end_date": None},
    })
    mock_tools(monkeypatch, {"add_memory_event": {"status": "duplicate", "event_id": 5}})
    out = await apply_memory_token(token)
    assert out["status"] == "applied" and out.get("note")


@pytest.mark.asyncio
async def test_apply_unknown_type_rejected(monkeypatch):
    token = encode_memory_token({"type": "weird"})
    mock_tools(monkeypatch)
    with pytest.raises(ValueError):
        await apply_memory_token(token)
