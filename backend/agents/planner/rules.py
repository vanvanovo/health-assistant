# backend/agents/planner/rules.py
# 计划图的规则层:调档(完成率/体感)+ 事件约束(伤病/出差)+ 计划项本地校验。
# 纪律:规则定边界,LLM 只在边界内组织内容。

from __future__ import annotations

from datetime import date, timedelta

# 调档阈值(演示口径,可配置)
RATE_UP = 0.8            # 完成率 ≥80% 且不疲劳 → 加量
RATE_DOWN = 0.5          # 完成率 <50% → 降档
TIRED_RATIO_DOWN = 0.4   # 疲惫占比 ≥40% → 降档

KINDS = {"workout", "habit", "diet"}
DEFAULT_WORKOUT_DAYS = [0, 2, 4, 6]   # 周一/三/五/日


def target_week_start(today: date) -> date:
    """默认目标周 = 下周(周一)。"""
    this_monday = today - timedelta(days=today.weekday())
    return this_monday + timedelta(days=7)


def _repeat_titles(history_plans: list[dict], threshold: int = 4) -> list[str]:
    """近 N 周连续出现(从最近一周往前数)的 workout 标题;history_plans 需按周从新到旧。"""
    streak: dict[str, int] = {}
    for week in history_plans:
        titles = set(week.get("titles") or [])
        for t in list(streak):
            if t not in titles:
                del streak[t]
        for t in titles:
            streak[t] = streak.get(t, 0) + 1
    return [t for t, n in streak.items() if n >= threshold]


def compute_constraints(
    summary: dict, profile: dict, events: list[dict], week_start: date,
    recent_items: list[dict] | None = None, history_plans: list[dict] | None = None,
) -> dict:
    """规则算约束:强度档 + 目标周轻量日 + 规避项 + 可用训练日 + 恢复日/换项(完整调档表)。"""
    checkin = summary.get("checkin") or {}
    rate = checkin.get("completion_rate")
    feel = summary.get("feeling") or {}
    total_feel = sum(feel.get(k, 0) or 0 for k in ("good", "normal", "tired"))
    tired_ratio = (feel.get("tired", 0) or 0) / total_feel if total_feel else 0.0

    reasons: list[str] = []
    if rate is not None and rate >= RATE_UP and tired_ratio <= 0.25:
        level = "up"
        reasons.append(f"完成率 {int(rate * 100)}% 且状态不疲惫,可以小幅加量")
    elif (rate is not None and rate < RATE_DOWN) or tired_ratio >= TIRED_RATIO_DOWN:
        level = "down"
        if rate is not None and rate < RATE_DOWN:
            reasons.append(f"完成率 {int(rate * 100)}% 偏低,先降强度、拆小目标")
        if tired_ratio >= TIRED_RATIO_DOWN:
            reasons.append(f"疲惫占比 {int(tired_ratio * 100)}%,需要更多恢复")
    else:
        level = "keep"
        reasons.append("完成率与体感处于中间区,保持当前强度")

    # 连续低体感(≤2)≥2 次 → 建议恢复日
    low_streak, cur = 0, 0
    scored = sorted(
        [it for it in (recent_items or []) if it.get("feeling_score") is not None and it.get("date")],
        key=lambda x: str(x.get("date")),
    )
    for it in scored:
        if int(it["feeling_score"]) <= 2:
            cur += 1
            low_streak = max(low_streak, cur)
        else:
            cur = 0
    recovery_days = 1 if low_streak >= 2 else 0
    if recovery_days:
        reasons.append(f"连续 {low_streak} 次体感偏低,本周插入恢复日")

    repeated = _repeat_titles(history_plans or [], threshold=4)
    if repeated:
        reasons.append("重复训练建议换项:" + "、".join(repeated))

    week_end = week_start + timedelta(days=6)
    light_dates: dict[str, str] = {}
    avoids: list[str] = []
    event_notes: list[str] = []
    for ev in events or []:
        try:
            s = date.fromisoformat(ev["start_date"])
            e = date.fromisoformat(ev["end_date"]) if ev.get("end_date") else None
        except (KeyError, ValueError):
            continue
        if e is not None and e < week_start:
            continue          # 目标周之前已结束的事件
        if s > week_end:
            continue          # 目标周之后才开始的事件
        overlap_start = max(s, week_start)
        overlap_end = min(e or week_end, week_end)
        event_notes.append(f"{ev['description']}({overlap_start.isoformat()}~{overlap_end.isoformat()})")
        if ev.get("kind") == "travel":
            d = overlap_start
            while d <= overlap_end:
                light_dates[d.isoformat()] = "出差日:安排拉伸/散步等轻量内容"
                d += timedelta(days=1)
        if ev.get("kind") == "injury":
            avoids.append(f"避免加重伤处:{ev['description']}(替换为低冲击动作)")

    pref = (profile or {}).get("schedule_pref") or {}
    workout_days = pref.get("workout_days") or DEFAULT_WORKOUT_DAYS
    workout_days = [int(x) for x in workout_days if 0 <= int(x) <= 6] or DEFAULT_WORKOUT_DAYS
    allowed_days = [
        d for d in sorted(set(workout_days))
        if (week_start + timedelta(days=d)).isoformat() not in light_dates
    ]

    return {
        "level": level,
        "reasons": reasons,
        "rate": rate,
        "tired_ratio": round(tired_ratio, 2),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "workout_days": allowed_days,
        "light_dates": light_dates,
        "avoid": avoids,
        "events": event_notes,
        "recovery_days": recovery_days,
        "swap_suggestions": [f"「{t}」已连续 4 周以上,建议换一个同类动作" for t in repeated],
        "evidence": {
            "completion_rate": rate,
            "tired_ratio": round(tired_ratio, 2),
            "low_feeling_streak": low_streak,
            "events": event_notes,
        },
    }


def validate_plan_items(items, week_start: date) -> list[dict]:
    """本地校验 LLM 生成的计划项(与 MCP save_plan 同口径);不合法抛 ValueError。"""
    if not isinstance(items, list) or not items:
        raise ValueError("计划项为空")
    if len(items) > 30:
        raise ValueError("计划项超过 30 条")
    normalized: list[dict] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"第 {i} 项不是对象")
        try:
            d = date.fromisoformat(str(it.get("date", ""))[:10])
        except ValueError as e:
            raise ValueError(f"第 {i} 项日期非法:{it.get('date')}") from e
        if not (week_start <= d <= week_start + timedelta(days=6)):
            raise ValueError(f"第 {i} 项日期不在目标周:{d.isoformat()}")
        kind = it.get("kind")
        if kind not in KINDS:
            raise ValueError(f"第 {i} 项 kind 非法:{kind}")
        title = str(it.get("title") or "").strip()
        if not title or len(title) > 128:
            raise ValueError(f"第 {i} 项标题为空或过长")
        minutes = it.get("est_minutes")
        if minutes is not None and not (0 <= int(minutes) <= 300):
            raise ValueError(f"第 {i} 项 est_minutes 越界:{minutes}")
        intensity = it.get("intensity")
        if intensity is not None and not (1 <= int(intensity) <= 3):
            raise ValueError(f"第 {i} 项 intensity 越界:{intensity}")
        normalized.append({
            "date": d.isoformat(), "kind": kind, "title": title,
            "detail": str(it.get("detail") or "")[:300] or None,
            "est_minutes": int(minutes) if minutes is not None else None,
            "intensity": int(intensity) if intensity is not None else None,
        })
    return normalized
