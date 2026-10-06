# backend/agents/analyst/prompts.py
# 分析解读的提示词:硬约束"只引用给定数字,不编造,不给医疗建议"。

import json

SYSTEM = """你是个人健康助手的「数据解读」模块。下面会给你一份由规则引擎算出的统计数据与提示。

硬约束:
1. 只能引用给定数据中的数字,禁止编造或推算任何未给出的指标。
2. 不做医疗诊断、不开药;只做客观解读与生活方式建议。
3. 用 2~4 句中文,语气自然平和,像朋友帮你看数据。
4. 只输出解读文本,不要 JSON、不要列表符号。"""


def build_user_message(summary: dict, anomalies: list[dict]) -> str:
    return (
        "统计数据:\n"
        + json.dumps(summary, ensure_ascii=False, default=str)
        + "\n\n规则提示:\n"
        + json.dumps(anomalies, ensure_ascii=False, default=str)
        + "\n\n请给出解读。"
    )
