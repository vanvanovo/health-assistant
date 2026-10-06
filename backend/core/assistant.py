# backend/core/assistant.py
# 助手主图:LangGraph StateGraph(route → dispatch → finalize),挂 checkpointer 实现多轮记忆。
# - SSE 事件协议不变:routing / progress / card / token / meta / done(节点内 custom stream 推送)
# - 记忆:PostgresSaver(主)→ MemorySaver(降级)→ 无(不阻塞对话)
# - thread_id = 单用户演示账号;重启网关后历史仍在(Postgres 模式)

from __future__ import annotations

import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from backend.agents.common.result import agent_result
from backend.config import get_settings
from backend.core import orchestrator
from backend.core.logger import get_logger

logger = get_logger(__name__)


class AssistantState(TypedDict, total=False):
    messages: Annotated[list, add_messages]   # 多轮对话历史(checkpointer 持久化)
    user_input: str
    route: dict          # mode: rule|clarify|dispatch;intents/slots
    results: list[dict]
    degraded: bool
    started_at: float


def _emit(event: str, data: dict) -> None:
    """节点内向 SSE 流推送事件(stream_mode='custom')。"""
    get_stream_writer()({"event": event, "data": data})


# ── 节点 ─────────────────────────────────────────────────────
async def route_node(state) -> dict:
    t0 = time.time()
    user_input = state.get("user_input") or ""
    history = state.get("messages") or []

    # ① 规则前置(零 Token)
    pf = orchestrator.prefilter(user_input)
    if pf:
        _emit("routing", {"intents": ["rule"], "slots": {}, "confidence": 1.0})
        async for ev in orchestrator._stream_message(pf["message"]):
            _emit(ev["event"], ev["data"])
        return {
            "route": {"mode": "rule"},
            "messages": [HumanMessage(user_input), AIMessage(pf["message"])],
            "started_at": t0,
        }

    # ② 意图识别(注入近期对话,支持指代)
    _emit("progress", {"stage": "routing", "label": "正在识别意图…"})
    try:
        routed = await orchestrator.route_intent(user_input, history=history)
    except Exception as e:  # noqa: BLE001
        logger.warning("router.failed", error=str(e))
        _emit("routing", {"intents": ["out_of_scope"], "slots": {}, "confidence": 0.0})
        async for ev in orchestrator._stream_message(orchestrator.FALLBACK_REPLY):
            _emit(ev["event"], ev["data"])
        return {
            "route": {"mode": "clarify"},
            "degraded": True,
            "messages": [HumanMessage(user_input), AIMessage(orchestrator.FALLBACK_REPLY)],
            "started_at": t0,
        }

    _emit(
        "routing",
        {
            "intents": [i["name"] for i in routed["intents"]],
            "slots": routed["slots"],
            "confidence": routed["confidence"],
        },
    )

    # ③ 追问(信息不足)
    if routed["need_clarify"]:
        clarify = routed["clarify"] or "能再多说一点吗?比如时间、项目或具体数字。"
        async for ev in orchestrator._stream_message(clarify):
            _emit(ev["event"], ev["data"])
        return {
            "route": {"mode": "clarify"},
            "messages": [HumanMessage(user_input), AIMessage(clarify)],
            "started_at": t0,
        }

    return {
        "route": {"mode": "dispatch", "intents": routed["intents"], "slots": routed["slots"]},
        "messages": [HumanMessage(user_input)],
        "started_at": t0,
    }


def after_route(state) -> str:
    return "dispatch" if (state.get("route") or {}).get("mode") == "dispatch" else "finalize"


async def dispatch_node(state) -> dict:
    route = state.get("route") or {}
    results: list[dict] = []
    for it in route.get("intents") or []:
        name, query = it["name"], it["query"]
        _emit("progress", {"stage": name, "label": f"正在处理:{orchestrator.INTENT_LABELS.get(name, name)}…"})
        try:
            result = await orchestrator._dispatch(name, query, route.get("slots") or {})
        except Exception as e:  # noqa: BLE001
            logger.error("dispatch.failed", intent=name, error=str(e))
            result = agent_result(name, "failed", "这项暂时处理不了,稍后再试或换个说法。", degraded=True)
        results.append(result)
        if result.get("card"):
            _emit("card", result["card"])

    combined = "\n\n".join(r.get("message") or "" for r in results if r.get("message"))
    async for ev in orchestrator._stream_message(combined):
        _emit(ev["event"], ev["data"])
    return {
        "results": results,
        "degraded": any(r.get("degraded") for r in results),
        "messages": [AIMessage(combined)],
    }


async def finalize_node(state) -> dict:
    elapsed = int((time.time() - (state.get("started_at") or time.time())) * 1000)
    _emit("meta", {"elapsed_ms": elapsed, "degraded": bool(state.get("degraded")), "sources": []})
    _emit("done", {})
    return {}


# ── 装配 ─────────────────────────────────────────────────────
def build_assistant_graph(checkpointer=None):
    g = StateGraph(AssistantState)
    g.add_node("route", route_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, {"dispatch": "dispatch", "finalize": "finalize"})
    g.add_edge("dispatch", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


_graph = None
_saver_kind = "none"
_pool = None


def reset_assistant(checkpointer=None) -> None:
    global _graph
    _graph = build_assistant_graph(checkpointer)


def saver_kind() -> str:
    return _saver_kind


def thread_id() -> str:
    return f"user:{get_settings().demo_username}"


async def init_assistant() -> str:
    """启动时装配:PostgresSaver 主 → MemorySaver 降级(记忆不可用不阻塞对话)。"""
    global _pool, _saver_kind
    s = get_settings()
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        dsn = (
            f"postgresql://{s.pg_user}:{s.pg_password}"
            f"@{s.pg_host}:{s.pg_port}/{s.pg_db}"
        )
        pool = AsyncConnectionPool(
            conninfo=dsn, min_size=1, max_size=4, open=False,
            timeout=10.0,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        _pool = pool
        reset_assistant(saver)
        _saver_kind = "postgres"
        logger.info("assistant.checkpointer", kind="postgres")
    except Exception as e:  # noqa: BLE001
        logger.warning("assistant.checkpointer_fallback", error=str(e))
        from langgraph.checkpoint.memory import MemorySaver

        reset_assistant(MemorySaver())
        _saver_kind = "memory"
    return _saver_kind


async def shutdown_assistant() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None


async def run_chat(user_input: str):
    """会话主链路(异步事件流):SSE 事件顺序与 V1 完全一致。"""
    if _graph is None:
        reset_assistant(None)
    config = {"configurable": {"thread_id": thread_id()}}
    state = {"user_input": user_input, "results": [], "degraded": False}
    async for chunk in _graph.astream(state, config=config, stream_mode="custom"):
        if isinstance(chunk, dict) and "event" in chunk:
            yield chunk
