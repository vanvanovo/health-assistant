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


ACTIVE_WORKOUT_TYPES = {"running", "strength", "other"}


def summarize_records(records: list[dict], checkin_items: list[dict] | None = None) -> dict:
    """聚合统计(纯规则)。

    records: [{date, workout_type, workout_minutes, weight_kg, sleep_hours, feeling}]
    checkin_items: [{status, kind, date, title}] —— 可选,用于计划完成率
    """
    dates: list[str] = []
    for r in records:
        d = r.get("date")
        if d:
            dates.append(d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10])
    date_from = min(dates) if dates else None
    date_to = max(dates) if dates else None

    workout_days = 0
    total_minutes = 0
    by_type: dict[str, int] = {}
    for r in records:
        m = r.get("workout_minutes") or 0
        wtype = str(r.get("workout_type") or "")
        # 训练日判定:有分钟数,或运动类型属于真运动(rest/空不算);
        # “跑了5公里但没给时长”也算训练日,只是不计入分钟数(绝不编造时长)
        if (m and int(m) > 0) or wtype in ACTIVE_WORKOUT_TYPES:
            workout_days += 1
            if m and int(m) > 0:
                total_minutes += int(m)
            if wtype:
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


# ── P7:四维健康评分(全部规则化、可解释、可单测)──────────────
def _training_streak(records: list[dict]) -> int:
    """最长连续训练天数(有分钟数或运动类型属于真运动;rest/空不算)。"""
    from datetime import date as _date

    days = set()
    for r in records:
        d = r.get("date")
        wtype = str(r.get("workout_type") or "")
        m = r.get("workout_minutes") or 0
        if d and ((m and int(m) > 0) or wtype in ACTIVE_WORKOUT_TYPES):
            try:
                days.add(_date.fromisoformat(str(d)[:10]))
            except ValueError:
                continue
    if not days:
        return 0
    ordered = sorted(days)
    best = cur = 1
    for prev, nxt in zip(ordered, ordered[1:]):
        if (nxt - prev).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def compute_radar(records: list[dict], meal_days: int, weeks: int = 4) -> dict:
    """四维评分(0~100,公式见注释,可解释):
    运动 = min(100, 训练天数 ÷ (4×周数) × 100)(目标 4 次/周)
    睡眠 = 100 − |平均睡眠 − 7.5| × 25(− 平均 <6.5 再 −10),截断 0~100
    饮食 = 有饮食记录的天数 ÷ (7×周数) × 100
    恢复 = 100 − 疲惫占比 × 80 − max(0, 最长连续训练天数 − 2) × 10,截断 0~100
    """
    summary = summarize_records(records)
    weeks = max(int(weeks), 1)
    total_days = weeks * 7

    workout_days = (summary.get("workout") or {}).get("days") or 0
    sport = min(100.0, workout_days / (4.0 * weeks) * 100)

    sleep_avg = (summary.get("sleep") or {}).get("avg")
    if sleep_avg is None:
        sleep = 60.0
    else:
        sleep = 100.0 - abs(sleep_avg - 7.5) * 25 - (10.0 if sleep_avg < 6.5 else 0.0)
        sleep = max(0.0, min(100.0, sleep))

    diet = max(0.0, min(100.0, int(meal_days) / total_days * 100))

    feel = summary.get("feeling") or {}
    total_feel = sum(feel.get(k, 0) or 0 for k in ("good", "normal", "tired"))
    tired_ratio = (feel.get("tired", 0) or 0) / total_feel if total_feel else 0.0
    streak = _training_streak(records)
    recovery = 100.0 - tired_ratio * 80 - max(0, streak - 2) * 10
    recovery = max(0.0, min(100.0, recovery))

    return {
        "weeks": weeks,
        "scores": {
            "sport": round(sport),
            "sleep": round(sleep),
            "diet": round(diet),
            "recovery": round(recovery),
        },
        "detail": {
            "workout_days": workout_days,
            "sleep_avg": sleep_avg,
            "meal_days": int(meal_days),
            "tired_ratio": round(tired_ratio, 2),
            "training_streak": streak,
            "overall": round((sport + sleep + diet + recovery) / 4),
        },
    }
