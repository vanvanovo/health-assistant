# backend/agents/diet/rules.py
# 饮食规则层(纯函数,可单测):
#   1) 份量模板:把"一碗/一个/一杯/一片/一把"折算为克数中值(演示口径,卡上标注"估算")
#   2) 每日需求公式(对齐《V2 实施计划》§3.2)
#   3) 食谱校验:候选范围 + 热量带(±15%)+ 蛋白下限(90%)

from __future__ import annotations

# ── 份量模板 ─────────────────────────────────────────────────
PORTION_GRAMS: dict[str, float] = {
    "一碗": 200, "一份": 150, "一个": 55, "一杯": 250,
    "一片": 30, "一把": 15, "一盒": 150, "一瓶": 500, "半个": 28,
}

# 食物 × 份量的精确覆盖(优先于通用模板)
FOOD_PORTION_OVERRIDE: dict[tuple[str, str], float] = {
    ("米饭", "一碗"): 200,
    ("糙米饭", "一碗"): 200,
    ("鸡蛋", "一个"): 55,
    ("牛奶", "一杯"): 250,
    ("豆浆", "一杯"): 250,
    ("酸奶", "一杯"): 150,
    ("面包", "一片"): 30,
    ("核桃", "一把"): 15,
    ("杏仁", "一把"): 15,
    ("腰果", "一把"): 15,
}


def resolve_amount(food: str, portion: str | None, amount_g: float | None) -> float:
    """解析克数:显式克数优先;否则按份量模板;都拿不到 → 抛 ValueError(不猜)。"""
    if amount_g is not None:
        try:
            g = float(amount_g)
        except (TypeError, ValueError):
            raise ValueError(f"克数不合法:{amount_g}") from None
        if 0 < g <= 2000:
            return round(g, 1)
        raise ValueError(f"克数不合法:{amount_g}(需 0~2000g)")

    p = str(portion or "").strip()
    if p:
        for (food_key, portion_key), grams in FOOD_PORTION_OVERRIDE.items():
            if food_key in food and portion_key in p:
                return float(grams)
        for portion_key, grams in PORTION_GRAMS.items():
            if portion_key in p:
                return float(grams)
    raise ValueError(f"无法确定「{food}」的份量(需要克数或常见份量,如“一碗”)")


# ── 每日需求公式 ─────────────────────────────────────────────
def compute_daily_needs(weight_kg: float, goal: str | None, training_day: bool = False) -> dict:
    """维持热量 = 体重×30(+训练日 200);减脂 −400(下限 1300),增肌 +300;
    蛋白:减脂 1.8 / 增肌 2.0 / 保持 1.4 g/kg;脂肪 ≥0.8g/kg;碳水 = 剩余热量 ÷ 4。"""
    w = float(weight_kg)
    goal = (goal or "保持健康").strip()

    kcal = w * 30 + (200 if training_day else 0)
    if "减脂" in goal:
        kcal -= 400
    elif "增肌" in goal:
        kcal += 300
    kcal = max(kcal, 1300.0)

    if "减脂" in goal:
        protein_ratio = 1.8
    elif "增肌" in goal:
        protein_ratio = 2.0
    else:
        protein_ratio = 1.4
    protein = w * protein_ratio
    fat = max(w * 0.8, kcal * 0.25 / 9.0)
    carb = max((kcal - protein * 4 - fat * 9) / 4.0, 50.0)

    return {
        "kcal": round(kcal),
        "protein_g": round(protein, 1),
        "fat_g": round(fat, 1),
        "carb_g": round(carb, 1),
        "goal": goal,
        "weight_kg": round(w, 1),
        "training_day": bool(training_day),
    }


def check_plan_totals(totals: dict, needs: dict) -> list[str]:
    """校验食谱总计;返回问题列表(空 = 通过)。热量带 ±15%,蛋白 ≥90%。"""
    issues: list[str] = []
    kcal = float(totals.get("kcal") or 0)
    need_kcal = float(needs.get("kcal") or 0)
    if need_kcal > 0 and not (need_kcal * 0.85 <= kcal <= need_kcal * 1.15):
        issues.append(f"总热量 {kcal:.0f} 不在需求 {need_kcal:.0f}±15% 区间")
    protein = float(totals.get("protein_g") or 0)
    need_protein = float(needs.get("protein_g") or 0)
    if need_protein > 0 and protein < need_protein * 0.9:
        issues.append(f"蛋白质 {protein:.0f}g 低于需求 {need_protein:.0f}g 的 90%")
    return issues
