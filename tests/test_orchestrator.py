# tests/test_orchestrator.py
# 编排层离线用例:规则前置 / 多意图串行 / 卡片与时序 / 降级 / 打卡两模式。

from datetime import date, timedelta

import pytest

from backend.agents.common.result import agent_result
from backend.core import orchestrator

TODAY = date.today().isoformat()


async def collect(message: str):
    return [ev async for ev in orchestrator.run_chat(message)]


def events(evs, name):
    return [e for e in evs if e["event"] == name]


def full_text(evs):
    return "".join(e["data"]["text"] for e in events(evs, "token"))


def patch_route(monkeypatch, routed=None, exc=None):
    async def fake(user_input, today=None):
        if exc:
            raise exc
        return routed

    monkeypatch.setattr(orchestrator, "route_intent", fake)


def patch_agents(monkeypatch, recorder=None, analyst=None, planner=None):
    async def r(*a, **kw):
        return recorder or agent_result("recorder", "ok", "已记录。", card={"type": "record_confirm", "payload": {}})

    async def a(*a, **kw):
        return analyst or agent_result("analyst", "ok", "统计完成。", card={"type": "stats", "payload": {}})

    async def p(*a, **kw):
        return planner or agent_result("planner", "ok", "计划完成。", card={"type": "plan", "payload": {}})

    monkeypatch.setattr(orchestrator, "run_recorder", r)
    monkeypatch.setattr(orchestrator, "run_analyst", a)
    monkeypatch.setattr(orchestrator, "run_planner", p)


@pytest.mark.asyncio
async def test_rule_prefilter_zero_dispatch(monkeypatch):
    patch_route(monkeypatch, exc=AssertionError("规则命中不应调用 LLM 路由"))
    evs = await collect("你好")
    assert [e["data"]["intents"] for e in events(evs, "routing")] == [["rule"]]
    assert "个人健康助手" in full_text(evs)
    assert events(evs, "meta")[0]["data"]["degraded"] is False
    assert evs[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_record_flow_card_before_tokens(monkeypatch):
    patch_route(monkeypatch, {"intents": [{"name": "record", "query": "今天跑了5公里"}], "slots": {}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    patch_agents(monkeypatch, recorder=agent_result("recorder", "ok", "已记录 10-06:跑步 30 分钟。", card={"type": "record_confirm", "payload": {"record": {}}}))
    evs = await collect("今天跑了5公里")
    assert [e["data"]["intents"] for e in events(evs, "routing")] == [["record"]]
    stages = [e["data"]["stage"] for e in events(evs, "progress")]
    assert "record" in stages
    assert full_text(evs) == "已记录 10-06:跑步 30 分钟。"
    idx_card = evs.index(events(evs, "card")[0])
    idx_tok = evs.index(events(evs, "token")[0])
    assert idx_card < idx_tok


@pytest.mark.asyncio
async def test_multi_intent_serial(monkeypatch):
    patch_route(monkeypatch, {"intents": [{"name": "analyze", "query": "看状态"}, {"name": "plan", "query": "排计划"}], "slots": {"days": 7}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    patch_agents(
        monkeypatch,
        analyst=agent_result("analyst", "ok", "本周状态不错。", card={"type": "stats", "payload": {}}),
        planner=agent_result("planner", "ok", "计划已生成。", card={"type": "plan", "payload": {}}),
    )
    evs = await collect("看看这周状态,顺便排下周计划")
    stages = [e["data"]["stage"] for e in events(evs, "progress")]
    assert stages == ["routing", "analyze", "plan"]
    text = full_text(evs)
    assert "本周状态不错。" in text and "计划已生成。" in text
    assert len(events(evs, "card")) == 2


@pytest.mark.asyncio
async def test_analyze_days_slot_used(monkeypatch):
    captured = {}

    async def fake_analyst(date_from=None, date_to=None, today=None):
        captured.update(date_from=date_from, date_to=date_to)
        return agent_result("analyst", "ok", "ok", card={"type": "stats", "payload": {}})

    patch_route(monkeypatch, {"intents": [{"name": "analyze", "query": "这周状态"}], "slots": {"days": 7}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    monkeypatch.setattr(orchestrator, "run_analyst", fake_analyst)
    await collect("看看这周状态")
    assert captured["date_from"] == (date.today() - timedelta(days=6)).isoformat()
    assert captured["date_to"] == TODAY


@pytest.mark.asyncio
async def test_router_failure_degrades(monkeypatch):
    patch_route(monkeypatch, exc=RuntimeError("路由挂了"))
    evs = await collect("记录一下")
    assert "换个说法" in full_text(evs)
    assert events(evs, "meta")[0]["data"]["degraded"] is True


@pytest.mark.asyncio
async def test_dispatch_failure_degrades(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("agent 挂了")

    patch_route(monkeypatch, {"intents": [{"name": "record", "query": "记录"}], "slots": {}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    monkeypatch.setattr(orchestrator, "run_recorder", boom)
    evs = await collect("记录一下")
    assert "暂时处理不了" in full_text(evs)
    assert events(evs, "meta")[0]["data"]["degraded"] is True


@pytest.mark.asyncio
async def test_need_clarify_no_dispatch(monkeypatch):
    patch_route(monkeypatch, {"intents": [{"name": "record", "query": "记一下"}], "slots": {}, "need_clarify": True, "clarify": "要记录哪天的什么数据?", "confidence": 0.6})
    called = {"n": 0}

    async def should_not_call(*a, **kw):
        called["n"] += 1
        return agent_result("recorder", "ok", "x")

    monkeypatch.setattr(orchestrator, "run_recorder", should_not_call)
    evs = await collect("记一下")
    assert full_text(evs) == "要记录哪天的什么数据?"
    assert called["n"] == 0


def _fake_tool_factory(calls, plan):
    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        if name == "get_active_plan":
            return {"status": "success", "data": plan}
        if name == "upsert_checkin":
            return {"status": "success", "data": {"item": {"id": arguments.get("plan_item_id") or 99, "status": arguments.get("status")}, "ad_hoc": arguments.get("plan_item_id") is None}}
        if name == "get_plan_progress":
            return {"status": "success", "data": {"progress": {"completion_rate": 0.67}}}
        return {"status": "success", "data": {}}

    return fake


@pytest.mark.asyncio
async def test_checkin_in_plan(monkeypatch):
    calls = []
    plan = {"week_start": "2026-10-05", "items": [
        {"id": 11, "date": TODAY, "kind": "workout", "title": "慢跑 5km", "status": "pending"},
    ]}
    patch_route(monkeypatch, {"intents": [{"name": "checkin", "query": "今天的训练完成了"}], "slots": {}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    monkeypatch.setattr(orchestrator.tools, "call_tool", _fake_tool_factory(calls, plan))
    evs = await collect("今天的训练完成了")
    assert "打卡成功" in full_text(evs) and "67%" in full_text(evs)
    card = events(evs, "card")[0]["data"]
    assert card["payload"]["mode"] == "checkin"
    upsert = next(c for c in calls if c["name"] == "upsert_checkin")
    assert upsert["args"]["plan_item_id"] == 11
    assert upsert["args"]["status"] == "done"


@pytest.mark.asyncio
async def test_checkin_no_plan_adhoc(monkeypatch):
    calls = []
    patch_route(monkeypatch, {"intents": [{"name": "checkin", "query": "今天走路了"}], "slots": {}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    monkeypatch.setattr(orchestrator.tools, "call_tool", _fake_tool_factory(calls, {"week_start": "2026-10-05", "items": []}))
    evs = await collect("今天走路了")
    assert "自由打卡" in full_text(evs)
    card = events(evs, "card")[0]["data"]
    assert card["payload"]["mode"] == "checkin_adhoc"
    upsert = next(c for c in calls if c["name"] == "upsert_checkin")
    assert upsert["args"]["kind"] == "habit"


@pytest.mark.asyncio
async def test_out_of_scope_message(monkeypatch):
    patch_route(monkeypatch, {"intents": [{"name": "out_of_scope", "query": "讲个笑话"}], "slots": {}, "need_clarify": False, "clarify": "", "confidence": 0.9})
    evs = await collect("讲个笑话")
    assert "记录健康数据" in full_text(evs)
