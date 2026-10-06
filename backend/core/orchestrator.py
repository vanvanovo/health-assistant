# backend/core/orchestrator.py
# 会话编排辅助层:规则前置 / 意图分发 / 打卡处理 / 消息切片(供 assistant 主图调用)。
# 事件流主链路见 backend/core/assistant.py(routing / progress / card / token / meta / done)。

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from backend.agents.analyst.graph import run_analyst
from backend.agents.common import llm_json, tools
from backend.agents.common.result import agent_result
from backend.agents.common.utils import short_hash
from backend.agents.diet.graph import run_diet
from backend.agents.memory.handler import run_memory
from backend.agents.planner.graph import run_planner
from backend.agents.recorder.graph import run_recorder
from backend.config import get_settings
from backend.core import cache, safety
from backend.core.a2a_client import call_health_rag
from backend.core.logger import get_logger
from backend.core.router import prefilter, route_intent

logger = get_logger(__name__)

INTENT_LABELS = {
    "record": "记录", "checkin": "打卡", "analyze": "数据分析", "plan": "计划",
    "diet": "饮食", "memory": "记忆", "knowledge": "知识问答", "out_of_scope": "其他",
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

    # P10:同一计划项并发打卡 → 短锁串行化(Redis 不可用降级放行)
    lock_name = f"lock:checkin:{target['id']}"
    try:
        lock_token = await cache.acquire_lock(lock_name)
    except cache.LockBusy:
        return agent_result("checkin", "ok", "这个打卡项正在处理另一笔请求,请稍后重试。")
    try:
        res = await tools.call_tool(
            "upsert_checkin",
            {
                "plan_item_id": target["id"], "status": status, "feeling_score": feeling,
                "idempotency_key": f"ck-{target['id']}-{today}-{short_hash(user_input)}",
            },
        )
    finally:
        await cache.release_lock(lock_name, lock_token)
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


KNOWLEDGE_SYSTEM = (
    "你是健康知识助手,知识库暂时不可用。"
    "请只给出最保守的生活方式常识建议:不编造具体数字、不诊断、不开药;"
    "语言简洁 2~3 句,结尾注明仅供参考。"
)


async def _handle_knowledge(query: str) -> dict:
    """知识问答:A2A RAG 优先;失败/关闭 → llm_direct 降级(标注知识库不可用)。"""
    s = get_settings()
    if s.rag_via_a2a:
        try:
            data = await call_health_rag(query)
            mode = data.get("answer_mode") or "rag"
            answer = (data.get("answer") or "").strip()
            sources = data.get("sources") or []
            safety_info = data.get("safety") or {"level": "ok"}

            if safety_info.get("level") == "high":
                return agent_result(
                    "knowledge", "ok", answer,
                    data={"answer_mode": mode, "safety": safety_info},
                )
            if "仅供参考" not in answer:
                answer += "\n\n" + safety.DISCLAIMER
            card = {"type": "sources", "payload": {"sources": sources, "answer_mode": mode}} if sources else None
            res = agent_result(
                "knowledge", "ok", answer, card=card,
                data={"answer_mode": mode, "sources": sources, "safety": safety_info},
            )
            if mode != "rag":
                res["degraded"] = True
            return res
        except Exception as e:  # noqa: BLE001
            logger.warning("knowledge.a2a_failed", error=str(e)[:200])
    else:
        logger.info("knowledge.a2a_disabled")

    # 降级:不冒充知识库;LLM 直答 + 明确标注
    try:
        text = await llm_json.chat_text(
            [
                {"role": "system", "content": KNOWLEDGE_SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
        )
    except Exception:  # noqa: BLE001
        text = "知识库与模型暂时都不可用,请稍后再试。"
    text = str(text).strip() + "\n\n(知识库暂不可用,以上为通用建议)\n\n" + safety.DISCLAIMER
    return agent_result("knowledge", "ok", text, degraded=True)


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
    if name == "memory":
        return await run_memory(query, today=today)
    if name == "knowledge":
        return await _handle_knowledge(query)
    return agent_result("router", "ok", OUT_OF_SCOPE_REPLY)
