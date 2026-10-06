# tests/test_alerts.py
# 预警规则离线用例(纯函数)。

from datetime import date, timedelta

from backend.core.alerts import evaluate_alerts

TODAY = date(2026, 10, 6)


def rec(d: date, **kw) -> dict:
    base = {
        "date": d.isoformat(), "workout_type": None, "workout_minutes": None,
        "sleep_hours": None, "weight_kg": None, "feeling": None,
    }
    base.update(kw)
    return base


def rules(alerts: list[dict]) -> list[str]:
    return [a["rule"] for a in alerts]


def test_sleep_debt_two_consecutive_nights():
    records = [
        rec(TODAY - timedelta(days=1), sleep_hours=5.5),
        rec(TODAY, sleep_hours=5.8),
    ]
    assert "sleep_debt" in rules(evaluate_alerts(records, None, TODAY))


def test_sleep_debt_single_night_not_triggered():
    records = [rec(TODAY, sleep_hours=5.5)]
    assert "sleep_debt" not in rules(evaluate_alerts(records, None, TODAY))


def test_sleep_debt_reset_by_good_night():
    records = [
        rec(TODAY - timedelta(days=2), sleep_hours=5.0),
        rec(TODAY - timedelta(days=1), sleep_hours=7.5),
        rec(TODAY, sleep_hours=5.5),
    ]
    assert "sleep_debt" not in rules(evaluate_alerts(records, None, TODAY))


def test_overtraining_three_consecutive_intense_days():
    records = [
        rec(TODAY - timedelta(days=2), workout_type="running", workout_minutes=60),
        rec(TODAY - timedelta(days=1), workout_type="strength", workout_minutes=40),
        rec(TODAY, workout_type="running", workout_minutes=55),
    ]
    assert "overtraining" in rules(evaluate_alerts(records, None, TODAY))


def test_overtraining_broken_by_light_day():
    records = [
        rec(TODAY - timedelta(days=2), workout_type="running", workout_minutes=60),
        rec(TODAY - timedelta(days=1), workout_type="running", workout_minutes=30),
        rec(TODAY, workout_type="running", workout_minutes=55),
    ]
    assert "overtraining" not in rules(evaluate_alerts(records, None, TODAY))


def test_weight_fluctuation_over_1pct():
    records = [
        rec(TODAY - timedelta(days=6), weight_kg=68.0),
        rec(TODAY, weight_kg=67.0),   # 1.47%
    ]
    hit = rules(evaluate_alerts(records, None, TODAY))
    assert "weight_fluctuation" in hit and "weight_surge" not in hit


def test_weight_surge_over_2pct_has_doctor_hint():
    records = [
        rec(TODAY - timedelta(days=6), weight_kg=68.0),
        rec(TODAY, weight_kg=66.0),   # 2.94%
    ]
    alerts = evaluate_alerts(records, None, TODAY)
    surge = [a for a in alerts if a["rule"] == "weight_surge"]
    assert surge and "咨询医生" in surge[0]["message"]


def test_record_gap():
    records = [rec(TODAY - timedelta(days=8), weight_kg=68.0)]
    assert "record_gap" in rules(evaluate_alerts(records, None, TODAY))


def test_adherence_low():
    records = [rec(TODAY, sleep_hours=7.5)]
    assert "adherence_low" in rules(evaluate_alerts(records, 0.3, TODAY))


def test_clean_data_no_alerts():
    records = [
        rec(TODAY - timedelta(days=2), sleep_hours=7.5, weight_kg=68.0, workout_type="running", workout_minutes=30),
        rec(TODAY, sleep_hours=7.6, weight_kg=68.0),
    ]
    assert evaluate_alerts(records, 0.8, TODAY) == []
