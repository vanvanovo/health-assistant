# backend/core/alerts.py
# 异常预警规则(P8):全部纯函数、可单测;阈值是演示口径,可配置。
# 输入:近 14 天记录(升序)、近 14 天完成率;输出:预警列表(rule/level/message)。

from __future__ import annotations

from datetime import date, timedelta

SLEEP_LOW = 6.0              # 睡眠债:连续 2 天 < 6h
WEIGHT_WARN_PCT = 1.0        # 一周体重变化 > 1% → warn
WEIGHT_SEEK_DOCTOR_PCT = 2.0 # 一周体重变化 > 2% → 附就医提示
HIGH_MINUTES = 50            # 过训:连续 3 天高强度(>=50min 或 strength)
GAP_DAYS = 7                 # 记录中断:7 天未记录
ADHERENCE_LOW = 0.4          # 近两周完成率 < 40%
HISTORY_DAYS = 14


def _parse(d) -> date | None:
    if isinstance(d, date):
        return d
    if isinstance(d, str) and d.strip():
        try:
            return date.fromisoformat(d.strip()[:10])
        except ValueError:
            return None
    return None


def _is_intense(r: dict) -> bool:
    m = r.get("workout_minutes") or 0
    return (m and int(m) >= HIGH_MINUTES) or r.get("workout_type") == "strength"


def evaluate_alerts(records: list[dict], completion_rate_14d: float | None, today: date) -> list[dict]:
    """返回命中的预警列表;无命中返回空列表。"""
    out: list[dict] = []
    rows = sorted(
        [r for r in records if _parse(r.get("date"))],
        key=lambda r: str(r.get("date")),
    )

    # ① 睡眠债:连续 2 天 < 6h
    streak = 0
    for r in rows:
        s = r.get("sleep_hours")
        if s is not None and float(s) < SLEEP_LOW:
            streak += 1
            if streak >= 2:
                out.append({
                    "rule": "sleep_debt", "level": "warn",
                    "message": f"连续 {streak} 天睡眠不足 6 小时,建议今晚提前休息、降低明日强度",
                })
                break
        else:
            streak = 0

    # ② 过训:连续 3 个日历日高强度无休
    intense_streak = 0
    prev_day: date | None = None
    for r in rows:
        d = _parse(r.get("date"))
        if d is None:
            continue
        if _is_intense(r):
            intense_streak = intense_streak + 1 if prev_day and (d - prev_day).days == 1 else 1
        else:
            intense_streak = 0
        prev_day = d
        if intense_streak >= 3:
            out.append({
                "rule": "overtraining", "level": "warn",
                "message": "连续 3 天高强度训练没有休息,建议安排一天恢复(拉伸/散步)",
            })
            break

    # ③ 体重波动(近 7 天首末对比)
    window_start = today - timedelta(days=6)
    weights = [
        ( _parse(r.get("date")), float(r["weight_kg"]) )
        for r in rows
        if r.get("weight_kg") is not None and _parse(r.get("date")) and _parse(r.get("date")) >= window_start
    ]
    if len(weights) >= 2:
        first, last = weights[0][1], weights[-1][1]
        if first > 0:
            pct = abs(last - first) / first * 100
            if pct > WEIGHT_SEEK_DOCTOR_PCT:
                out.append({
                    "rule": "weight_surge", "level": "warn",
                    "message": f"一周体重变化 {pct:.1f}%(>2%),变化偏快;如伴随不适建议咨询医生",
                })
            elif pct > WEIGHT_WARN_PCT:
                out.append({
                    "rule": "weight_fluctuation", "level": "warn",
                    "message": f"一周体重变化 {pct:.1f}%,请关注饮食与水分摄入",
                })

    # ④ 记录中断:7 天未记录
    if rows:
        last_day = _parse(rows[-1].get("date"))
        if last_day and (today - last_day).days > GAP_DAYS:
            out.append({
                "rule": "record_gap", "level": "info",
                "message": f"已经 {(today - last_day).days} 天没有记录了,今天补一条吧",
            })
    else:
        out.append({"rule": "record_gap", "level": "info", "message": "最近没有任何记录,今天开始记一条吧"})

    # ⑤ 完成率低(近两周)
    if completion_rate_14d is not None and completion_rate_14d < ADHERENCE_LOW:
        out.append({
            "rule": "adherence_low", "level": "info",
            "message": f"近两周计划完成率仅 {int(completion_rate_14d * 100)}%,建议把目标拆小、降低强度",
        })

    return out


def alert_evidence(records: list[dict], today: date) -> dict:
    """预警判定所需的证据摘要(随消息 payload 落库,便于解释)。"""
    sleeps = [float(r["sleep_hours"]) for r in records if r.get("sleep_hours") is not None]
    return {
        "records": len(records),
        "sleep_avg": round(sum(sleeps) / len(sleeps), 2) if sleeps else None,
        "today": today.isoformat(),
    }
