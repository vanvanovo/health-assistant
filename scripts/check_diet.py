# scripts/check_diet.py
# P5 验收:饮食真实链路(记录估算 + 食谱推荐);结束自动复原演示数据。
# 前置:网关已启动(--port 8020)。
# 用法:python scripts/check_diet.py [--keep]

import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

from backend.agents.diet.graph import run_diet  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402

_ok, _fail = 0, 0
KEEP = "--keep" in sys.argv


def check(cond: bool, name: str) -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  [OK] {name}")
    else:
        _fail += 1
        print(f"  [FAIL] {name}")


async def main() -> int:
    configure_logging()
    today = date.today().isoformat()

    # 1) 记录估算:克数 + 份量模板
    r1 = await run_diet("午饭吃了200g鸡胸肉和一碗米饭", today=today)
    card1 = r1.get("card") or {}
    payload1 = card1.get("payload") or {}
    items = payload1.get("items") or []
    check(r1["status"] == "ok" and card1.get("type") == "diet", "记录 → 饮食卡(ok)")
    check(len(items) >= 2 and any("鸡胸" in str(i.get("food")) for i in items), "明细含鸡胸肉")
    check(
        any("米饭" in str(i.get("food")) and abs(float(i.get("amount_g") or 0) - 200) < 1 for i in items),
        "「一碗」米饭 → 200g(份量模板)",
    )
    totals1 = payload1.get("totals") or {}
    check(float(totals1.get("kcal") or 0) > 300, f"热量换算 {totals1.get('kcal')} kcal")
    check(payload1.get("day_totals") is not None, "返回当日累计")

    # 2) 食谱推荐:需求 + 候选约束 + 热量带
    r2 = await run_diet("帮我配明天的三餐", today=today)
    card2 = r2.get("card") or {}
    payload2 = card2.get("payload") or {}
    check(r2["status"] == "ok" and payload2.get("mode") == "recommend", "推荐 → 食谱卡(ok)")
    needs = payload2.get("needs") or {}
    totals2 = payload2.get("totals") or {}
    need_kcal = float(needs.get("kcal") or 0)
    kcal2 = float(totals2.get("kcal") or 0)
    check(need_kcal > 0 and need_kcal * 0.85 <= kcal2 <= need_kcal * 1.15,
          f"热量带达标({kcal2:.0f} / 需求 {need_kcal:.0f})")
    check(float(totals2.get("protein_g") or 0) >= float(needs.get("protein_g") or 0) * 0.9,
          f"蛋白达标({totals2.get('protein_g')}g / 需求 {needs.get('protein_g')}g)")
    meals = payload2.get("meals") or {}
    check(all(k in meals for k in ("breakfast", "lunch", "dinner")), "三餐齐全")
    food_count = sum(len(v) for v in meals.values())
    check(food_count >= 6, f"食谱食物数 {food_count} ≥ 6")

    # 3) 复原演示数据
    if not KEEP:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 复原演示数据 …")
        await regen()

    print(f"\nCHECK DIET: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
