# backend/agents/recorder/graph.py
# 记录图装配 + 对外运行入口。

from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph

from backend.agents.common.states import RecorderState

from . import nodes


def route_after_validate(state) -> str:
    return state.get("next_step", "upsert")


def build_recorder_graph():
    g = StateGraph(RecorderState)
    g.add_node("parse", nodes.parse_node)
    g.add_node("validate", nodes.validate_node)
    g.add_node("clarify", nodes.clarify_node)
    g.add_node("upsert", nodes.upsert_node)
    g.add_node("confirm", nodes.confirm_node)

    g.add_edge(START, "parse")
    g.add_edge("parse", "validate")
    g.add_conditional_edges(
        "validate", route_after_validate, {"clarify": "clarify", "upsert": "upsert"}
    )
    g.add_edge("clarify", END)
    g.add_edge("upsert", "confirm")
    g.add_edge("confirm", END)
    return g.compile()


_graph = None


def get_recorder_graph():
    global _graph
    if _graph is None:
        _graph = build_recorder_graph()
    return _graph


async def run_recorder(user_input: str, today: str | None = None) -> dict:
    """执行记录链路,返回统一结果契约(status: ok / clarify / failed)。"""
    state = {"user_input": user_input, "today": today or date.today().isoformat()}
    final = await get_recorder_graph().ainvoke(state)
    return final.get("result") or {
        "agent": "recorder", "status": "failed", "message": "未产生结果",
        "card": None, "data": None, "degraded": True,
    }
