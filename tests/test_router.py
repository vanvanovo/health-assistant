# tests/test_router.py
# 意图路由离线用例:规则前置 + LLM 输出归一/白名单/槽位清洗。

import pytest

from backend.agents.common import llm_json
from backend.core import router as intent_router

TODAY = "2026-10-06"


def test_prefilter_greeting():
    hit = intent_router.prefilter("你好")
    assert hit and "个人健康助手" in hit["message"]


def test_prefilter_thanks():
    hit = intent_router.prefilter("谢谢!")
    assert hit and "不客气" in hit["message"]


def test_prefilter_help():
    assert intent_router.prefilter("你能做什么")


def test_prefilter_empty():
    hit = intent_router.prefilter("   ")
    assert hit and "记录" in hit["message"]


def test_prefilter_business_not_hit():
    # 带业务内容的消息不能被规则误伤
    assert intent_router.prefilter("你好,帮我记录今天跑了5公里") is None
    assert intent_router.prefilter("今天跑了5公里,体重68") is None


@pytest.mark.asyncio
async def test_route_intent_multi(monkeypatch):
    async def fake(messages, **kw):
        return {
            "intents": [
                {"name": "analyze", "query": "看看这周状态"},
                {"name": "plan", "query": "排下周计划"},
            ],
            "slots": {"days": 7}, "need_clarify": False, "clarify": "", "confidence": 0.92,
        }

    monkeypatch.setattr(llm_json, "chat_json", fake)
    r = await intent_router.route_intent("看看这周状态,顺便排下周计划", today=TODAY)
    assert [i["name"] for i in r["intents"]] == ["analyze", "plan"]
    assert r["slots"]["days"] == 7
    assert r["confidence"] == 0.92


@pytest.mark.asyncio
async def test_route_intent_invalid_name_becomes_out_of_scope(monkeypatch):
    async def fake(messages, **kw):
        return {"intents": [{"name": "eat", "query": "吃什么"}], "confidence": "bad"}

    monkeypatch.setattr(llm_json, "chat_json", fake)
    r = await intent_router.route_intent("吃什么", today=TODAY)
    assert r["intents"][0]["name"] == "out_of_scope"
    assert r["confidence"] == 0.8


@pytest.mark.asyncio
async def test_route_intent_slots_clamped(monkeypatch):
    async def fake(messages, **kw):
        return {
            "intents": ["checkin"],
            "slots": {"days": 999, "status": "done", "feeling_score": 9},
            "confidence": 0.5,
        }

    monkeypatch.setattr(llm_json, "chat_json", fake)
    r = await intent_router.route_intent("打卡", today=TODAY)
    assert r["slots"]["days"] == 180
    assert r["slots"]["status"] == "done"
    assert "feeling_score" not in r["slots"]


@pytest.mark.asyncio
async def test_route_intent_empty_intents(monkeypatch):
    async def fake(messages, **kw):
        return {"intents": [], "need_clarify": True, "clarify": "想做什么?"}

    monkeypatch.setattr(llm_json, "chat_json", fake)
    r = await intent_router.route_intent("呃", today=TODAY)
    assert r["intents"][0]["name"] == "out_of_scope"
    assert r["need_clarify"] is True
    assert r["clarify"] == "想做什么?"


@pytest.mark.asyncio
async def test_route_intent_merges_same_name(monkeypatch):
    """同一天多项数据被模型拆成多个 record → 合并为一个(片段拼接)。"""
    async def fake(messages, **kw):
        return {
            "intents": [
                {"name": "record", "query": "今天慢跑30分钟"},
                {"name": "record", "query": "体重68.1"},
                {"name": "record", "query": "睡了7小时"},
            ],
            "confidence": 0.9,
        }

    monkeypatch.setattr(llm_json, "chat_json", fake)
    r = await intent_router.route_intent("今天慢跑 30 分钟,体重 68.1,睡了 7 小时", today=TODAY)
    assert [i["name"] for i in r["intents"]] == ["record"]
    assert r["intents"][0]["query"] == "今天慢跑30分钟、体重68.1、睡了7小时"


@pytest.mark.asyncio
async def test_route_intent_includes_history(monkeypatch):
    captured = {}

    async def fake(messages, **kw):
        captured["messages"] = messages
        return {"intents": ["analyze"], "slots": {"days": 7}, "confidence": 0.9}

    monkeypatch.setattr(llm_json, "chat_json", fake)

    class _Msg:
        def __init__(self, mtype, content):
            self.type, self.content = mtype, content

    history = [_Msg("human", "我最近一个月状态怎么样?"), _Msg("ai", "近30天训练12次")]
    r = await intent_router.route_intent("那这周呢?", today=TODAY, history=history)
    system_content = captured["messages"][0]["content"]
    assert "近期对话" in system_content
    assert "我最近一个月状态怎么样?" in system_content
    assert r["slots"]["days"] == 7


@pytest.mark.asyncio
async def test_route_intent_cached_without_history(monkeypatch):
    """P10:无上下文时走缓存;带历史时不走缓存(避免指代语义漂移)。"""
    from backend.core import cache as cache_mod

    class _FakeRedis:
        def __init__(self):
            self.store: dict = {}

        async def get(self, k):
            return self.store.get(k)

        async def set(self, k, v, nx=False, ex=None):
            self.store[k] = v
            return True

        async def delete(self, k):
            self.store.pop(k, None)

    fake_store = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_client", lambda: fake_store)
    calls = {"n": 0}

    async def fake_llm(messages, **kw):
        calls["n"] += 1
        return {"intents": ["record"], "slots": {}, "confidence": 0.9}

    monkeypatch.setattr(llm_json, "chat_json", fake_llm)
    r1 = await intent_router.route_intent("今天慢跑5公里,体重68", today=TODAY)
    r2 = await intent_router.route_intent("今天慢跑5公里,体重68", today=TODAY)
    assert calls["n"] == 1 and r1 == r2

    class _Msg:
        def __init__(self, mtype, content):
            self.type, self.content = mtype, content

    await intent_router.route_intent("今天慢跑5公里,体重68", today=TODAY, history=[_Msg("human", "x")])
    assert calls["n"] == 2
