# backend/agents/common/states.py
# 三张 LangGraph 图的状态定义(TypedDict,total=False = 节点返回部分字段做合并)。
# 约定:每个图的终态都会写入 result(统一 Agent 结果契约,见 result.py)。

from typing import TypedDict


class RecorderState(TypedDict, total=False):
    """记录图:抽取 → 校验 →(追问 | UPSERT)→ 确认。"""

    user_input: str
    today: str
    extracted: dict          # LLM 原始抽取
    cleaned: dict            # 校验/归一后的字段
    errors: list[str]        # 校验错误(非空 → 追问)
    need_clarify: bool
    next_step: str           # clarify | upsert
    upsert_res: dict         # MCP 返回
    result: dict             # 统一结果契约


class AnalystState(TypedDict, total=False):
    """分析图:统计(规则)→ 异常检测(规则)→ LLM 解读 → 卡片。"""

    user_input: str
    today: str
    date_from: str
    date_to: str
    summary: dict            # get_range_summary 的事实数据
    anomalies: list[dict]    # 规则命中的异常/提示
    interpretation: str      # LLM 解读(只基于事实)
    result: dict


class PlannerState(TypedDict, total=False):
    """计划图:上下文 → 调档(规则)→ 生成(LLM)→ 保存(版本化)→ 卡片。"""

    user_input: str
    today: str
    week_start: str          # 目标周周一(默认下周一)
    summary: dict            # 近 30 天统计
    profile: dict            # 画像
    events: list[dict]       # 有效事件记忆
    constraints: dict        # 规则约束(强度档/轻量日/规避项)
    llm_plan: dict           # LLM 生成的计划 JSON(已本地校验)
    saved: dict              # MCP 保存结果
    result: dict
