# tests/test_stats.py
# 统计规则离线用例(纯函数,不连库)。

from backend.core.stats import summarize_checkins, summarize_records


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
