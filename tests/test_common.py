# tests/test_common.py
# 公共层离线用例:JSON 解析容错 + chat_json 重试。

import pytest

from backend.agents.common import llm_json
from backend.agents.common.llm_json import parse_json_block


def test_parse_plain_json():
    assert parse_json_block('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    assert parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_with_surrounding_text():
    assert parse_json_block('好的,这是结果: {"a": 1} 请查收') == {"a": 1}


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_json_block("我不会 JSON")


@pytest.mark.asyncio
async def test_chat_json_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def fake_text(messages, **kw):
        calls["n"] += 1
        return "抱歉,我直接回答你" if calls["n"] == 1 else '{"ok": true}'

    monkeypatch.setattr(llm_json, "chat_text", fake_text)
    out = await llm_json.chat_json([{"role": "user", "content": "x"}], retries=1)
    assert out == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_chat_json_all_bad_raises(monkeypatch):
    async def fake_text(messages, **kw):
        return "还是不会"

    monkeypatch.setattr(llm_json, "chat_text", fake_text)
    with pytest.raises(ValueError):
        await llm_json.chat_json([{"role": "user", "content": "x"}], retries=1)
