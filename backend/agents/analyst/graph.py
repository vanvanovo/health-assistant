# backend/agents/analyst/graph.py
# 分析图装配 + 对外运行入口。

from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph

from backend.agents.common.states import AnalystState

from . import nodes


def build_analyst_graph():
    g = StateGraph(AnalystState)
    g.add_node("collect", nodes.collect_node)
    g.add_node("anomaly", nodes.anomaly_node)
    g.add_node("interpret", nodes.interpret_node)
    g.add_node("format", nodes.format_node)

    g.add_edge(START, "collect")
    g.add_edge("collect", "anomaly")
    g.add_edge("anomaly", "interpret")
    g.add_edge("interpret", "format")
    g.add_edge("format", END)
    return g.compile()


_graph = None


def get_analyst_graph():
    global _graph
    if _graph is None:
        _graph = build_analyst_graph()
    return _graph


async def run_analyst(
    date_from: str | None = None,
    date_to: str | None = None,
    today: str | None = None,
) -> dict:
    """执行分析链路(默认近 30 天),返回统一结果契约。"""
    state = {
        "today": today or date.today().isoformat(),
        "date_from": date_from or "",
        "date_to": date_to or "",
    }
    final = await get_analyst_graph().ainvoke(state)
    return final.get("result") or {
        "agent": "analyst", "status": "failed", "message": "未产生结果",
        "card": None, "data": None, "degraded": True,
    }
