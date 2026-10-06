# tests/test_stats.py
# 统计规则离线用例(纯函数,不连库)。

from backend.core.stats import compute_radar, summarize_checkins, summarize_records


def _rec(d, **kw):
    base = {"date": d, "workout_type": None, "workout_minutes": None,
            "weight_kg": None, "sleep_hours": None, "feeling": None}
    base.update(kw)
    return base


def test_summarize_records_basic():
    from datetime import date
    records = [
        _rec(date(2026, 9, 1), workout_type="running", workout_minutes=30, weight_kg=70.0, sleep_hours=7.0, feeling="good"),
        _rec(date(2026, 9, 2), weight_kg=69.8, sleep_hours=6.5, feeling="normal"),
        _rec(date(2026, 9, 3), workout_type="strength", workout_minutes=45, weight_kg=69.6, sleep_hours=7.5, feeling="tired"),
        _rec(date(2026, 9, 4), workout_type="rest", workout_minutes=0, weight_kg=69.7, sleep_hours=8.0, feeling="good"),
    ]
    s = summarize_records(records)
    assert s["recorded_days"] == 4
    assert s["workout"]["days"] == 2
    assert s["workout"]["total_minutes"] == 75
    assert s["workout"]["by_type"] == {"running": 1, "strength": 1}
    assert s["weight"]["delta"] == round(69.7 - 70.0, 2)
    assert s["weight"]["points"] == 4
    assert s["sleep"]["nights"] == 4
    assert s["feeling"] == {"good": 2, "normal": 1, "tired": 1}
    assert s["checkin"] is None


def test_summarize_records_empty():
    s = summarize_records([])
    assert s["recorded_days"] == 0
    assert s["weight"] is None and s["sleep"] is None
    assert s["workout"] == {"days": 0, "total_minutes": 0, "by_type": {}}


def test_summarize_checkins_rate():
    items = [
        {"status": "done"}, {"status": "done"}, {"status": "partial"},
        {"status": "missed"}, {"status": "pending"}, {"status": "pending"},
    ]
    c = summarize_checkins(items)
    assert c["done"] == 2 and c["partial"] == 1 and c["missed"] == 1 and c["pending"] == 2
    assert c["elapsed"] == 4
    # (2 + 0.5) / 4 = 0.625 → 0.62(四舍五入到两位)
    assert c["completion_rate"] == 0.62


def test_summarize_checkins_all_pending():
    c = summarize_checkins([{"status": "pending"}, {"status": "pending"}])
    assert c["elapsed"] == 0
    assert c["completion_rate"] is None


def test_workout_day_without_minutes_still_counts():
    """“跑了5公里但没给时长”:也算训练日,只是不计分钟数(绝不编造时长)。"""
    from datetime import date
    records = [
        _rec(date(2026, 9, 1), workout_type="running", workout_minutes=None, weight_kg=70.0),
        _rec(date(2026, 9, 2), workout_type="rest", workout_minutes=None),
    ]
    s = summarize_records(records)
    assert s["workout"]["days"] == 1
    assert s["workout"]["total_minutes"] == 0
    assert s["workout"]["by_type"] == {"running": 1}


# ── P7:四维评分 ──────────────────────────────────────────────
def _radar_records(workout_days: int, sleep_hours: float, tired: int = 0, good: int = 10):
    """构造 28 天记录:前 workout_days 天为训练日。"""
    from datetime import date, timedelta
    start = date(2026, 9, 1)
    rows = []
    for i in range(28):
        d = start + timedelta(days=i)
        is_workout = i < workout_days
        rows.append(_rec(
            d,
            workout_type="running" if is_workout else None,
            workout_minutes=30 if is_workout else None,
            sleep_hours=sleep_hours,
            feeling="tired" if i < tired else ("good" if i < tired + good else None),
        ))
    return rows


def test_compute_radar_sport_and_diet():
    records = _radar_records(workout_days=8, sleep_hours=7.5)
    r = compute_radar(records, meal_days=14, weeks=4)
    assert r["scores"]["sport"] == 50        # 8 / 16
    assert r["scores"]["diet"] == 50         # 14 / 28


def test_compute_radar_sleep():
    records = _radar_records(workout_days=0, sleep_hours=7.5)
    assert compute_radar(records, 0, 4)["scores"]["sleep"] == 100
    records = _radar_records(workout_days=0, sleep_hours=6.2)
    assert compute_radar(records, 0, 4)["scores"]["sleep"] in (57, 58)   # 100-32.5-10


def test_compute_radar_recovery_streak_penalty():
    # 连续 5 天训练 → 恢复分 100 − 0 × 80 − (5−2) × 10 = 70
    records = _radar_records(workout_days=5, sleep_hours=7.5, tired=0)
    r = compute_radar(records, 0, 4)
    assert r["detail"]["training_streak"] == 5
    assert r["scores"]["recovery"] == 70


def test_compute_radar_tired_penalty():
    records = _radar_records(workout_days=0, sleep_hours=7.5, tired=8, good=0)
    r = compute_radar(records, 0, 4)
    assert r["detail"]["tired_ratio"] == 1.0
    assert r["scores"]["recovery"] == 20     # 100 − 80


def test_compute_radar_sleep_missing_uses_conservative():
    r = compute_radar([], 0, 4)
    assert r["scores"]["sleep"] == 60
    assert r["scores"]["sport"] == 0 and r["scores"]["diet"] == 0


def test_summarize_records_accepts_string_dates():
    """雷达链路走过 JSON(str 日期):兼容 str/date 两种输入(回归用例)。"""
    records = [
        {"date": "2026-09-01", "workout_type": "running", "workout_minutes": 30, "weight_kg": 70.0, "sleep_hours": 7.0, "feeling": "good"},
        {"date": "2026-09-02", "workout_type": None, "workout_minutes": None, "weight_kg": 69.9, "sleep_hours": 7.2, "feeling": "normal"},
    ]
    s = summarize_records(records)
    assert s["date_from"] == "2026-09-01" and s["date_to"] == "2026-09-02"
    r = compute_radar(records, meal_days=1, weeks=4)
    assert set(r["scores"]) == {"sport", "sleep", "diet", "recovery"}
