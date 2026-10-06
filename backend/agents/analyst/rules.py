# backend/agents/analyst/rules.py
# 分析图的规则层:全部可解释、可单测。阈值是演示口径(后续可进配置表)。

from __future__ import annotations

SLEEP_DEBT_AVG = 6.5          # 平均睡眠低于 6.5h(至少 3 晚)判为睡眠债
FATIGUE_TIRED_RATIO = 0.4     # 疲惫占比超过 40% 判为疲劳
WEEKLY_WEIGHT_CHANGE = 1.0    # 折算周变化超过 ±1.0kg 判为变化过快
ADHERENCE_RATE = 0.5          # 完成率低于 50%(已执行 ≥4 项)判为偏低


def detect_anomalies(summary: dict) -> list[dict]:
    """基于统计事实出提示(纯规则);无命中则返回一条"状态平稳"。"""
    out: list[dict] = []

    sleep = summary.get("sleep") or {}
    if (sleep.get("nights") or 0) >= 3 and (sleep.get("avg") or 99) < SLEEP_DEBT_AVG:
        out.append({
            "rule": "sleep_debt", "level": "warn",
            "message": f"平均睡眠 {sleep['avg']} 小时,明显偏低,注意补觉与作息",
        })

    feel = summary.get("feeling") or {}
    total_feel = sum(feel.get(k, 0) or 0 for k in ("good", "normal", "tired"))
    if total_feel >= 5 and (feel.get("tired", 0) or 0) / total_feel > FATIGUE_TIRED_RATIO:
        out.append({
            "rule": "fatigue", "level": "warn",
            "message": f"{feel['tired']}/{total_feel} 天体感疲惫,建议降低强度或安排恢复日",
        })

    weight = summary.get("weight") or {}
    days = summary.get("recorded_days") or 0
    if weight and days >= 5:
        weekly = abs(weight["delta"]) / days * 7
        if weekly > WEEKLY_WEIGHT_CHANGE:
            direction = "下降" if weight["delta"] < 0 else "上升"
            out.append({
                "rule": "weight_change", "level": "warn",
                "message": f"体重按当前速度每周{direction}约 {weekly:.1f} kg,变化偏快",
            })

    checkin = summary.get("checkin") or {}
    if (checkin.get("elapsed") or 0) >= 4 and (checkin.get("completion_rate") or 1.0) < ADHERENCE_RATE:
        out.append({
            "rule": "adherence", "level": "info",
            "message": f"计划完成率仅 {int(checkin['completion_rate'] * 100)}%,建议把目标拆小一点",
        })

    if not out:
        out.append({"rule": "ok", "level": "info", "message": "各项指标在合理范围内,保持当前节奏"})
    return out
