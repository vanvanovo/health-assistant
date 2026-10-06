# backend/agents/common/result.py
# 统一 Agent 结果契约:三张图 + P4 编排层之间的稳定接口。

from __future__ import annotations


def agent_result(
    agent: str,
    status: str,
    message: str,
    *,
    card: dict | None = None,
    data: dict | None = None,
    degraded: bool = False,
) -> dict:
    """构造统一结果。

    status: ok(完成)/ clarify(缺参追问,正常业务态)/ failed(失败)
    card:   结构化卡片 {type, payload}(前端渲染用;无卡片为 None)
    data:   原始结构化数据(供编排层/日志使用)
    degraded: 是否走了降级路径
    """
    return {
        "agent": agent,
        "status": status,
        "message": message,
        "card": card,
        "data": data,
        "degraded": degraded,
    }
