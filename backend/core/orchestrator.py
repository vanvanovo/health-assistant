# backend/core/orchestrator.py
# 会话编排:规则前置 → 意图路由 → 多意图串行分发 → 卡片 + 打字机消息。
# 对外只暴露 run_chat(异步事件流):routing / progress / card / token / meta / done。
# V1 说明:token 事件按固定步长切片推送(前端已是 SSE 打字机);真·逐 token 流式为后续增强项。

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

from backend.agents.analyst.graph import run_analyst
from backend.agents.common import tools
from backend.agents.common.result import agent_result
from backend.agents.common.utils import short_hash
from backend.agents.diet.graph import run_diet
from backend.agents.planner.graph import run_planner
from backend.agents.recorder.graph import run_recorder
from backend.core.logger import get_logger
from backend.core.router import prefilter, route_intent

logger = get_logger(__name__)

INTENT_LABELS = {
    "record": "记录", "checkin": "打卡", "analyze": "数据分析", "plan": "计划",
    "diet": "饮食", "knowledge": "知识问答", "out_of_scope": "其他",
}
STATUS_CN = {"done": "完成", "partial": "部分完成", "missed": "未完成"}
STREAM_CHUNK = 14
STREAM_DELAY = 0.02

OUT_OF_SCOPE_REPLY = "我可以帮你:记录健康数据、打卡、看统计、排计划。试试换个说法?"
FALLBACK_REPLY = "刚才没太理解你的意思,换个说法再试试?比如「今天跑了 5 公里,体重 68.2」"


async def _stream_message(text: str):
    """把整段消息切成小块推送(token 事件),前端呈现打字机效果。"""
    text = text or ""
    if not text:
        return
    for i in range(0, len(text), STREAM_CHUNK):
        if i:
            await asyncio.sleep(STREAM_DELAY)
        yield {"event": "token", "data": {"text": text[i : i + STREAM_CHUNK]}}


def _status_from_text(text: str) -> str:
    t = text or ""
    if any(k in t for k in ("没做", "没完成", "没跑", "没练", "未完成", "跳过", "鸽了")):
        return "missed"
    if any(k in t for k in ("部分", "一半", "做了一些")):
        return "partial"
    return "done"


async def handle_checkin(user_input: str, slots: dict) -> dict:
    """打卡处理:优先打今天的计划项;没有则记一条自由打卡。"""
    today = date.today().isoformat()
    status = slots.get("status") or _status_from_text(user_input)
    feeling = slots.get("feeling_score")

    plan = tools.tool_data(await tools.call_tool("get_active_plan", {"date": today}), {})
    items = [it for it in (plan.get("items") or []) if it.get("date") == today]
    target = (
        next((it for it in items if it.get("kind") == "workout" and it.get("status") == "pending"), None)
        or next((it for it in items if it.get("status") == "pending"), None)
    )

    if target is None:
        res = await tools.call_tool(
            "upsert_checkin",
            {
                "date": today, "kind": "habit", "title": (user_input or "自由打卡")[:40],
                "status": status, "feeling_score": feeling,
                "idempotency_key": f"adhoc-{today}-{short_hash(user_input)}",
            },
        )
        data = tools.tool_data(res, {})
        if not data:
            return agent_result(
                "checkin", "failed",
                f"打卡失败:{res.get('message') if isinstance(res, dict) else res}", degraded=True,
            )
        return agent_result(
            "checkin", "ok", f"已记录一条自由打卡({STATUS_CN[status]})。",
            card={"type": "record_confirm", "payload": {"mode": "checkin_adhoc", "item": data.get("item")}},
            data={"item": data.get("item")},
        )

    res = await tools.call_tool(
        "upsert_checkin",
        {
            "plan_item_id": target["id"], "status": status, "feeling_score": feeling,
            "idempotency_key": f"ck-{target['id']}-{today}-{short_hash(user_input)}",
        },
    )
    data = tools.tool_data(res, {})
    if not data:
        return agent_result(
            "checkin", "failed",
            f"打卡失败:{res.get('message') if isinstance(res, dict) else res}", degraded=True,
        )
    progress = tools.tool_data(await tools.call_tool("get_plan_progress", {}), {}) or {}
    rate = (progress.get("progress") or {}).get("completion_rate")
    rate_txt = f",本周完成率 {int(rate * 100)}%" if isinstance(rate, (int, float)) else ""
    return agent_result(
        "checkin", "ok", f"打卡成功:{target['title']} → {STATUS_CN[status]}{rate_txt}。",
        card={"type": "record_confirm", "payload": {"mode": "checkin", "item": data.get("item"), "progress": progress}},
        data={"item": data.get("item"), "progress": progress},
    )


async def _dispatch(name: str, query: str, slots: dict) -> dict:
    today = date.today().isoformat()
    if name == "record":
        return await run_recorder(query, today=today)
    if name == "checkin":
        return await handle_checkin(query, slots)
    if name == "analyze":
        days = int(slots.get("days") or 30)
        date_from = (date.today() - timedelta(days=days - 1)).isoformat()
        return await run_analyst(date_from=date_from, date_to=today, today=today)
    if name == "plan":
        return await run_planner(query, today=today)
    if name == "diet":
        return await run_diet(query, today=today)
    if name == "knowledge":
        return agent_result("knowledge", "ok", "健康知识问答会在 V3 上线,先帮你记下需求~")
    return agent_result("router", "ok", OUT_OF_SCOPE_REPLY)


async def run_chat(user_input: str):
    """会话主链路(异步事件流)。"""
    t0 = time.time()

    # ① 规则前置(零 Token)
    pf = prefilter(user_input)
    if pf:
        yield {"event": "routing", "data": {"intents": ["rule"], "slots": {}, "confidence": 1.0}}
        async for ev in _stream_message(pf["message"]):
            yield ev
        yield {"event": "meta", "data": {"elapsed_ms": int((time.time() - t0) * 1000), "degraded": False, "sources": []}}
        yield {"event": "done", "data": {}}
        return

    # ② 意图识别
    yield {"event": "progress", "data": {"stage": "routing", "label": "正在识别意图…"}}
    try:
        routed = await route_intent(user_input)
    except Exception as e:  # noqa: BLE001
        logger.warning("router.failed", error=str(e))
        yield {"event": "routing", "data": {"intents": ["out_of_scope"], "slots": {}, "confidence": 0.0}}
        async for ev in _stream_message(FALLBACK_REPLY):
            yield ev
        yield {"event": "meta", "data": {"elapsed_ms": int((time.time() - t0) * 1000), "degraded": True, "sources": []}}
        yield {"event": "done", "data": {}}
        return

    yield {
        "event": "routing",
        "data": {
            "intents": [i["name"] for i in routed["intents"]],
            "slots": routed["slots"],
            "confidence": routed["confidence"],
        },
    }

    # ③ 追问(信息不足)
    if routed["need_clarify"]:
        clarify = routed["clarify"] or "能再多说一点吗?比如时间、项目或具体数字。"
        async for ev in _stream_message(clarify):
            yield ev
        yield {"event": "meta", "data": {"elapsed_ms": int((time.time() - t0) * 1000), "degraded": False, "sources": []}}
        yield {"event": "done", "data": {}}
        return

    # ④ 多意图串行分发(V1 串行;无依赖场景可并行,后续增强)
    results: list[dict] = []
    for it in routed["intents"]:
        name, query = it["name"], it["query"]
        yield {"event": "progress", "data": {"stage": name, "label": f"正在处理:{INTENT_LABELS.get(name, name)}…"}}
        try:
            result = await _dispatch(name, query, routed["slots"])
        except Exception as e:  # noqa: BLE001
            logger.error("dispatch.failed", intent=name, error=str(e))
            result = agent_result(name, "failed", "这项暂时处理不了,稍后再试或换个说法。", degraded=True)
        results.append(result)
        if result.get("card"):
            yield {"event": "card", "data": result["card"]}

    # ⑤ 汇总输出
    combined = "\n\n".join(r.get("message") or "" for r in results if r.get("message"))
    async for ev in _stream_message(combined):
        yield ev
    degraded = any(r.get("degraded") for r in results)
    yield {"event": "meta", "data": {"elapsed_ms": int((time.time() - t0) * 1000), "degraded": degraded, "sources": []}}
    yield {"event": "done", "data": {}}
