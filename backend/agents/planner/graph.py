# backend/agents/planner/graph.py
# 计划图装配 + 对外运行入口。

from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph

from backend.agents.common.states import PlannerState

from . import nodes


def build_planner_graph():
    g = StateGraph(PlannerState)
    g.add_node("context", nodes.context_node)
    g.add_node("adjust", nodes.adjust_node)
    g.add_node("generate", nodes.generate_node)
    g.add_node("save", nodes.save_node)
    g.add_node("format", nodes.format_node)

    g.add_edge(START, "context")
    g.add_edge("context", "adjust")
    g.add_edge("adjust", "generate")
    g.add_edge("generate", "save")
    g.add_edge("save", "format")
    g.add_edge("format", END)
    return g.compile()


_graph = None


def get_planner_graph():
    global _graph
    if _graph is None:
        _graph = build_planner_graph()
    return _graph


async def run_planner(
    user_input: str = "",
    week_start: str | None = None,
    today: str | None = None,
) -> dict:
    """执行计划链路(默认目标周 = 下周),返回统一结果契约。"""
    state = {
        "user_input": user_input,
        "today": today or date.today().isoformat(),
        "week_start": week_start or "",
    }
    final = await get_planner_graph().ainvoke(state)
    return final.get("result") or {
        "agent": "planner", "status": "failed", "message": "未产生结果",
        "card": None, "data": None, "degraded": True,
    }
