# backend/agents/diet/graph.py
# 饮食图装配(双模式)+ 对外运行入口。

from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph

from backend.agents.common.states import DietState

from . import nodes


def build_diet_graph():
    g = StateGraph(DietState)
    g.add_node("classify", nodes.classify_node)

    # log 分支
    g.add_node("match", nodes.match_node)
    g.add_node("calc", nodes.calc_node)
    g.add_node("save", nodes.save_node)
    g.add_node("format_log", nodes.format_log_node)

    # recommend 分支
    g.add_node("needs", nodes.needs_node)
    g.add_node("candidates", nodes.candidates_node)
    g.add_node("compose", nodes.compose_node)
    g.add_node("format_recommend", nodes.format_recommend_node)

    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", nodes.route_after_classify, {"log": "match", "recommend": "needs"})

    g.add_edge("match", "calc")
    g.add_edge("calc", "save")
    g.add_edge("save", "format_log")
    g.add_edge("format_log", END)

    g.add_edge("needs", "candidates")
    g.add_edge("candidates", "compose")
    g.add_edge("compose", "format_recommend")
    g.add_edge("format_recommend", END)
    return g.compile()


_graph = None


def get_diet_graph():
    global _graph
    if _graph is None:
        _graph = build_diet_graph()
    return _graph


async def run_diet(user_input: str, today: str | None = None) -> dict:
    """执行饮食链路(记录估算 / 食谱推荐),返回统一结果契约。"""
    state = {"user_input": user_input, "today": today or date.today().isoformat()}
    final = await get_diet_graph().ainvoke(state)
    return final.get("result") or {
        "agent": "diet", "status": "failed", "message": "未产生结果",
        "card": None, "data": None, "degraded": True,
    }
