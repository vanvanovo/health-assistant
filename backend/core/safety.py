# backend/core/safety.py
# 医疗安全边界(P9):关键词规则 + 统一话术;纯函数可单测。
# 纪律:不诊断、不开药、不做治疗方案;高危信号只做"就医/急救引导"。

from __future__ import annotations

DISCLAIMER = "以上内容仅供参考,不构成医疗建议。"

# 高危信号(演示口径;命中即停止一切健康建议)
HIGH_RISK_KEYWORDS = [
    "胸痛", "胸口疼", "胸闷", "心绞痛",
    "晕厥", "晕倒", "昏倒", "昏迷", "意识模糊",
    "呼吸困难", "喘不上气", "窒息", "咯血", "咳血", "咳出血", "吐血",
    "大出血", "剧烈头痛", "抽搐",
    "自伤", "自杀", "轻生", "不想活",
]

HIGH_RISK_REPLY = (
    "⚠️ 你描述的情况可能需要**立即就医**,请先不要自行处理或用药:\n"
    "· 如果症状正在发生:请立即拨打 **120** 或前往最近医院的急诊;\n"
    "· 本助手不能提供诊断或用药建议,也不会给出运动/饮食方案;\n"
    "· 如果你正有伤害自己的念头:请马上联系家人朋友陪着你,或拨打全国心理援助热线 **12356**。"
)


def check_high_risk(text: str) -> dict | None:
    """命中高危关键词 → 返回 {level, matched, reply};否则 None。"""
    t = text or ""
    hit = [k for k in HIGH_RISK_KEYWORDS if k in t]
    if hit:
        return {"level": "high", "matched": hit, "reply": HIGH_RISK_REPLY}
    return None
