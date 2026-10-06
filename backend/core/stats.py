# backend/core/stats.py
# 统计规则(纯函数,可单测):对话统计 / 数据看板 / 周报共用同一口径。
# 纪律:只算事实、不做解读;LLM 层只允许引用这里产出的数字。

from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize_checkins(items: list[dict]) -> dict:
    """计划完成率(纯规则):done 记 1、partial 记 0.5;pending 不计入分母。"""
    counts = {"done": 0, "partial": 0, "missed": 0, "pending": 0}
    for it in items:
        st = it.get("status")
        if st in counts:
            counts[st] += 1
    elapsed = counts["done"] + counts["partial"] + counts["missed"]
    rate = round((counts["done"] + 0.5 * counts["partial"]) / elapsed, 2) if elapsed else None
    return {**counts, "elapsed": elapsed, "completion_rate": rate}


def summarize_records(records: list[dict], checkin_items: list[dict] | None = None) -> dict:
    """聚合统计(纯规则)。

    records: [{date, workout_type, workout_minutes, weight_kg, sleep_hours, feeling}]
    checkin_items: [{status, kind, date, title}] —— 可选,用于计划完成率
    """
    dates = [r.get("date") for r in records if r.get("date")]
    date_from = min(dates).isoformat() if dates else None
    date_to = max(dates).isoformat() if dates else None

    workout_days = 0
    total_minutes = 0
    by_type: dict[str, int] = {}
    for r in records:
        m = r.get("workout_minutes") or 0
        if m and int(m) > 0:
            workout_days += 1
            total_minutes += int(m)
            wtype = str(r.get("workout_type") or "other")
            by_type[wtype] = by_type.get(wtype, 0) + 1

    weight_block = None
    weights = [(r.get("date"), _f(r.get("weight_kg"))) for r in records if _f(r.get("weight_kg")) is not None]
    if weights:
        weights.sort(key=lambda x: x[0])
        vals = [v for _, v in weights]
        weight_block = {
            "start": round(vals[0], 2),
            "end": round(vals[-1], 2),
            "delta": round(vals[-1] - vals[0], 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "points": len(vals),
        }

    sleep_block = None
    sleeps = [_f(r.get("sleep_hours")) for r in records if _f(r.get("sleep_hours")) is not None]
    if sleeps:
        sleep_block = {
            "avg": round(sum(sleeps) / len(sleeps), 2),
            "min": round(min(sleeps), 2),
            "max": round(max(sleeps), 2),
            "nights": len(sleeps),
        }

    feelings = {"good": 0, "normal": 0, "tired": 0}
    for r in records:
        f = r.get("feeling")
        if f in feelings:
            feelings[f] += 1

    checkin_block = summarize_checkins(checkin_items) if checkin_items is not None else None

    return {
        "date_from": date_from,
        "date_to": date_to,
        "recorded_days": len(dates),
        "workout": {"days": workout_days, "total_minutes": total_minutes, "by_type": by_type},
        "weight": weight_block,
        "sleep": sleep_block,
        "feeling": feelings,
        "checkin": checkin_block,
    }
