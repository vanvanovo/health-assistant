# tests/test_diet.py
# 饮食图离线用例(全 mock):份量模板 / 需求公式 / 记录估算 / 食谱编排约束。

import pytest

from backend.agents.common import llm_json, tools
from backend.agents.diet.graph import run_diet
from backend.agents.diet.rules import check_plan_totals, compute_daily_needs, resolve_amount

TODAY = "2026-10-06"
TOMORROW = "2026-10-07"


def food(name, category, kcal, protein, carb, fat):
    return {
        "food": name, "category": category, "calories": kcal, "protein_g": protein,
        "carbs_g": carb, "fat_g": fat, "per": "100g",
        "protein_density": round(protein / kcal, 3) if kcal else None,
    }


POOL = [
    food("鸡胸肉", "蛋白质", 133, 24.6, 0.6, 3.1),
    food("牛奶(全脂)", "蛋白质", 65, 3.3, 4.9, 3.6),
    food("无糖酸奶", "蛋白质", 62, 3.8, 4.9, 3.2),
    food("米饭(熟)", "碳水", 116, 2.6, 25.9, 0.3),
    food("燕麦片(干)", "碳水", 377, 15.0, 66.9, 6.7),
    food("西兰花", "蔬菜", 36, 4.1, 4.3, 0.6),
    food("菠菜", "蔬菜", 28, 2.6, 4.5, 0.3),
    food("蓝莓", "水果", 57, 0.7, 14.5, 0.3),
    food("橄榄油", "脂肪", 884, 0.0, 0.0, 100.0),
]

COMPOSE_OK = {
    "summary": "高蛋白减脂餐",
    "meals": {
        "breakfast": [{"food": "燕麦片(干)", "amount_g": 120}, {"food": "牛奶(全脂)", "amount_g": 300}],
        "lunch": [{"food": "鸡胸肉", "amount_g": 300}, {"food": "米饭(熟)", "amount_g": 250}],
        "dinner": [
            {"food": "无糖酸奶", "amount_g": 200},
            {"food": "西兰花", "amount_g": 250},
            {"food": "橄榄油", "amount_g": 10},
        ],
        "snack": [{"food": "蓝莓", "amount_g": 100}],
    },
}


def mock_llm_sequence(monkeypatch, responses):
    """按调用顺序返回预设 chat_json 结果。"""
    calls = {"n": 0}

    async def fake(messages, **kw):
        i = calls["n"]
        calls["n"] += 1
        r = responses[min(i, len(responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm_json, "chat_json", fake)
    return calls


def mock_tools(monkeypatch, *, day_intake=None, add_meal=None, profile=None, records=None, summary=None):
    calls = []

    async def fake(name, arguments, timeout=None):
        calls.append({"name": name, "args": arguments})
        if name == "search_food":
            pool = list(POOL)
            kw, cat = arguments.get("keyword"), arguments.get("category")
            if kw:
                pool = [f for f in pool if kw in f["food"]]
                pool.sort(key=lambda f: 0 if f["food"].startswith(kw) else 1)
            if cat:
                pool = [f for f in pool if f["category"] == cat]
            limit = arguments.get("limit", 10)
            return {"status": "success", "data": {"count": len(pool[:limit]), "total_matched": len(pool), "foods": pool[:limit]}}
        if name == "add_meal":
            return add_meal or {"status": "success", "data": {"inserted": len(arguments.get("items", [])), "totals": {"kcal": 0, "protein_g": 0}}}
        if name == "get_day_intake":
            return {"status": "success", "data": day_intake or {"total": {"kcal": 1200.0, "protein_g": 80.0}}}
        if name == "get_profile":
            return {"status": "success", "data": profile if profile is not None else {"goal": "减脂", "target_weight_kg": 68.0}}
        if name == "query_records":
            return {"status": "success", "data": records or {"records": [{"date": TODAY, "weight_kg": 68.0}]}}
        if name == "get_range_summary":
            return {"status": "success", "data": summary or {"workout": {"days": 2}}}
        return {"status": "success", "data": {}}

    monkeypatch.setattr(tools, "call_tool", fake)
    return calls


# ── 规则层 ───────────────────────────────────────────────────
def test_resolve_amount_explicit():
    assert resolve_amount("鸡胸肉", None, 150) == 150.0


def test_resolve_amount_portion_override():
    assert resolve_amount("米饭", "一碗", None) == 200.0
    assert resolve_amount("鸡蛋", "一个", None) == 55.0


def test_resolve_amount_unknown_raises():
    with pytest.raises(ValueError):
        resolve_amount("鸡胸肉", "一小坨", None)


def test_compute_daily_needs_goals():
    keep = compute_daily_needs(70, "保持健康", training_day=False)
    assert keep["kcal"] == 2100
    cut = compute_daily_needs(70, "减脂", training_day=False)
    assert cut["kcal"] == 1700 and cut["protein_g"] == 126.0
    cut_training = compute_daily_needs(70, "减脂", training_day=True)
    assert cut_training["kcal"] == 1900
    gain = compute_daily_needs(50, "增肌", training_day=False)
    assert gain["kcal"] == 1800 and gain["protein_g"] == 100.0


def test_compute_daily_needs_floor():
    assert compute_daily_needs(40, "减脂")["kcal"] == 1300   # 40*30-400=800 → 下限 1300


def test_check_plan_totals_bands():
    needs = {"kcal": 1600, "protein_g": 120.0}
    assert check_plan_totals({"kcal": 1500, "protein_g": 115}, needs) == []
    assert check_plan_totals({"kcal": 1200, "protein_g": 115}, needs)
    assert check_plan_totals({"kcal": 1500, "protein_g": 80}, needs)


# ── log 分支 ─────────────────────────────────────────────────
LOG_CLASSIFY = {
    "mode": "log", "date": TODAY, "meal_type": "lunch",
    "items": [
        {"food": "鸡胸肉", "amount_g": 200},
        {"food": "米饭", "amount_g": None, "portion": "一碗"},
    ],
}


@pytest.mark.asyncio
async def test_log_full_flow(monkeypatch):
    mock_llm_sequence(monkeypatch, [LOG_CLASSIFY])
    calls = mock_tools(monkeypatch)
    r = await run_diet("午饭吃了200g鸡胸肉和一碗米饭", today=TODAY)
    assert r["status"] == "ok"
    card = r["card"]
    assert card["type"] == "diet" and card["payload"]["mode"] == "log"
    items = card["payload"]["items"]
    assert items[0]["food"] == "鸡胸肉" and items[0]["kcal"] == 266.0
    assert items[1]["food"] == "米饭(熟)" and items[1]["amount_g"] == 200.0   # 一碗 → 200g
    assert card["payload"]["totals"]["kcal"] == 498.0
    assert "已记录午餐" in r["message"] and "1200" in r["message"]           # 含当日累计
    add_call = next(c for c in calls if c["name"] == "add_meal")
    assert add_call["args"]["items"][0]["kcal"] == 266.0
    assert add_call["args"]["idempotency_key"]


@pytest.mark.asyncio
async def test_log_unknown_food_reports(monkeypatch):
    parse = {"mode": "log", "meal_type": "lunch", "items": [{"food": "汉堡", "amount_g": 200}]}
    mock_llm_sequence(monkeypatch, [parse])
    calls = mock_tools(monkeypatch)
    r = await run_diet("午饭吃了个汉堡", today=TODAY)
    assert r["status"] == "failed" and "汉堡" in r["message"]
    assert not any(c["name"] == "add_meal" for c in calls)


@pytest.mark.asyncio
async def test_log_missing_amount_reports(monkeypatch):
    parse = {"mode": "log", "meal_type": "lunch", "items": [{"food": "鸡胸肉", "amount_g": None, "portion": None}]}
    mock_llm_sequence(monkeypatch, [parse])
    mock_tools(monkeypatch)
    r = await run_diet("午饭吃了点鸡胸肉", today=TODAY)
    assert r["status"] == "failed" and "份量" in r["message"]


# ── recommend 分支 ───────────────────────────────────────────
RECOMMEND_CLASSIFY = {"mode": "recommend", "date": TOMORROW}


@pytest.mark.asyncio
async def test_recommend_ok(monkeypatch):
    mock_llm_sequence(monkeypatch, [RECOMMEND_CLASSIFY, COMPOSE_OK])
    calls = mock_tools(monkeypatch)
    r = await run_diet("帮我配明天的三餐", today=TODAY)
    assert r["status"] == "ok"
    card = r["card"]
    assert card["payload"]["mode"] == "recommend"
    assert card["payload"]["needs"]["goal"] == "减脂"
    totals = card["payload"]["totals"]
    band = card["payload"]["needs"]["kcal"]
    assert band * 0.85 <= totals["kcal"] <= band * 1.15
    assert totals["protein_g"] >= card["payload"]["needs"]["protein_g"] * 0.9
    # 全部食物来自候选(营养库)
    allowed = {f["food"] for f in POOL}
    for slot_items in card["payload"]["meals"].values():
        for it in slot_items:
            assert it["food"] in allowed


@pytest.mark.asyncio
async def test_recommend_rejects_outside_candidate(monkeypatch):
    bad = {"summary": "x", "meals": {"lunch": [{"food": "汉堡", "amount_g": 100}]}}
    mock_llm_sequence(monkeypatch, [RECOMMEND_CLASSIFY, bad, bad])
    mock_tools(monkeypatch)
    with pytest.raises(ValueError):
        await run_diet("配个三餐", today=TODAY)


@pytest.mark.asyncio
async def test_recommend_retry_then_ok(monkeypatch):
    bad = {"summary": "x", "meals": {"lunch": [{"food": "汉堡", "amount_g": 100}]}}
    calls = mock_llm_sequence(monkeypatch, [RECOMMEND_CLASSIFY, bad, COMPOSE_OK])
    mock_tools(monkeypatch)
    r = await run_diet("配个三餐", today=TODAY)
    assert r["status"] == "ok"
    assert calls["n"] == 3      # classify + 失败1次 + 成功1次


@pytest.mark.asyncio
async def test_recommend_calorie_band_enforced(monkeypatch):
    tiny = {"summary": "x", "meals": {"lunch": [{"food": "菠菜", "amount_g": 50}]}}
    mock_llm_sequence(monkeypatch, [RECOMMEND_CLASSIFY, tiny, tiny])
    mock_tools(monkeypatch)
    with pytest.raises(ValueError):
        await run_diet("配个三餐", today=TODAY)
