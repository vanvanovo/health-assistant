# scripts/gen_demo_data.py
# P1:演示数据生成器(幂等:先清掉演示账号的数据与营养库,再重灌)。
# 设计目标:数据要有「真实感」—— 体重非线性缓降 + 噪声、每周 3~5 练、
#           高强度次日大概率 tired、含 1~2 周低谷、计划完成率有起伏。
# 用法:python scripts/gen_demo_data.py

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import asyncio  # noqa: E402
import random  # noqa: E402
from datetime import date, datetime, time, timedelta, timezone  # noqa: E402

import bcrypt  # noqa: E402
from sqlalchemy import delete, select, text  # noqa: E402

from backend.core.logger import configure_logging  # noqa: E402
from backend.db import models as M  # noqa: E402
from backend.db.base import dispose_engine, get_sessionmaker  # noqa: E402

DEMO_USERNAME = "health-demo"
DEMO_PASSWORD = "health-demo"
DAYS = 180
PLAN_WEEKS = 8
SEED = 42
TODAY = date.today()

# ── 营养库:100 条,每 100g 的热量/蛋白/碳水/脂肪(常见食物成分,演示用)──
NUTRITION: list[tuple[str, str, float, float, float, float]] = [
    # 蛋白质(20)
    ("鸡胸肉", "蛋白质", 133, 24.6, 0.6, 3.1),
    ("鸡蛋", "蛋白质", 144, 13.3, 2.8, 8.8),
    ("鸡蛋清", "蛋白质", 60, 11.6, 3.1, 0.1),
    ("牛里脊", "蛋白质", 107, 22.2, 2.4, 0.9),
    ("猪里脊", "蛋白质", 155, 20.2, 1.5, 7.9),
    ("鸡腿肉(去皮)", "蛋白质", 146, 18.0, 0.0, 8.0),
    ("虾仁", "蛋白质", 93, 18.6, 2.8, 0.8),
    ("三文鱼", "蛋白质", 139, 17.2, 0.0, 7.8),
    ("鳕鱼", "蛋白质", 88, 20.4, 0.5, 0.5),
    ("金枪鱼(水浸)", "蛋白质", 116, 25.2, 0.0, 1.0),
    ("北豆腐", "蛋白质", 116, 12.2, 3.0, 6.7),
    ("南豆腐", "蛋白质", 87, 6.2, 2.4, 5.8),
    ("豆干", "蛋白质", 197, 16.2, 11.5, 9.0),
    ("豆浆(无糖)", "蛋白质", 31, 3.0, 1.2, 1.6),
    ("牛奶(全脂)", "蛋白质", 65, 3.3, 4.9, 3.6),
    ("牛奶(脱脂)", "蛋白质", 34, 3.4, 5.0, 0.1),
    ("无糖酸奶", "蛋白质", 62, 3.8, 4.9, 3.2),
    ("希腊酸奶(无糖)", "蛋白质", 59, 10.0, 3.6, 0.4),
    ("黄豆(干)", "蛋白质", 390, 35.0, 34.2, 16.0),
    ("毛豆", "蛋白质", 131, 13.1, 10.5, 5.0),
    # 碳水(20)
    ("米饭(熟)", "碳水", 116, 2.6, 25.9, 0.3),
    ("糙米饭(熟)", "碳水", 112, 2.7, 23.5, 0.9),
    ("燕麦片(干)", "碳水", 377, 15.0, 66.9, 6.7),
    ("全麦面包", "碳水", 246, 9.0, 45.0, 3.4),
    ("馒头", "碳水", 223, 7.0, 47.0, 1.1),
    ("面条(煮)", "碳水", 110, 4.6, 24.3, 0.7),
    ("红薯(蒸)", "碳水", 86, 1.6, 20.1, 0.1),
    ("紫薯(蒸)", "碳水", 82, 2.3, 17.7, 0.2),
    ("土豆(蒸)", "碳水", 81, 2.0, 17.8, 0.2),
    ("玉米(煮)", "碳水", 112, 4.0, 22.8, 1.2),
    ("山药(蒸)", "碳水", 57, 1.9, 12.4, 0.2),
    ("芋头(蒸)", "碳水", 79, 2.2, 18.1, 0.2),
    ("小米粥", "碳水", 46, 1.4, 8.4, 0.7),
    ("藜麦(熟)", "碳水", 120, 4.4, 21.3, 1.9),
    ("荞麦面(熟)", "碳水", 99, 4.3, 20.0, 0.5),
    ("意大利面(熟)", "碳水", 158, 5.8, 30.9, 0.9),
    ("河粉(熟)", "碳水", 109, 1.8, 24.9, 0.3),
    ("米粉(熟)", "碳水", 97, 2.0, 22.0, 0.2),
    ("年糕", "碳水", 156, 3.0, 34.0, 0.5),
    ("饺子(猪肉白菜,熟)", "碳水", 240, 9.0, 28.0, 10.0),
    # 蔬菜(20)
    ("西兰花", "蔬菜", 36, 4.1, 4.3, 0.6),
    ("菠菜", "蔬菜", 28, 2.6, 4.5, 0.3),
    ("生菜", "蔬菜", 16, 1.3, 2.0, 0.3),
    ("黄瓜", "蔬菜", 16, 0.8, 2.9, 0.2),
    ("番茄", "蔬菜", 20, 0.9, 4.0, 0.2),
    ("胡萝卜", "蔬菜", 39, 1.0, 8.8, 0.2),
    ("大白菜", "蔬菜", 20, 1.5, 3.2, 0.1),
    ("油麦菜", "蔬菜", 15, 1.4, 2.1, 0.4),
    ("芹菜", "蔬菜", 22, 1.2, 4.5, 0.2),
    ("青椒", "蔬菜", 22, 1.0, 5.4, 0.2),
    ("西葫芦", "蔬菜", 19, 0.8, 3.8, 0.2),
    ("冬瓜", "蔬菜", 12, 0.4, 2.6, 0.2),
    ("苦瓜", "蔬菜", 22, 1.0, 4.9, 0.2),
    ("秋葵", "蔬菜", 45, 2.0, 7.6, 0.2),
    ("香菇", "蔬菜", 26, 2.2, 5.2, 0.3),
    ("金针菇", "蔬菜", 32, 2.4, 6.0, 0.4),
    ("木耳(水发)", "蔬菜", 27, 1.5, 6.0, 0.2),
    ("海带(水发)", "蔬菜", 14, 1.2, 2.1, 0.1),
    ("洋葱", "蔬菜", 40, 1.1, 9.0, 0.2),
    ("芦笋", "蔬菜", 22, 2.6, 4.9, 0.1),
    # 水果(20)
    ("苹果", "水果", 53, 0.4, 13.7, 0.2),
    ("香蕉", "水果", 93, 1.4, 22.0, 0.2),
    ("橙子", "水果", 48, 0.8, 11.1, 0.2),
    ("葡萄", "水果", 45, 0.4, 10.3, 0.3),
    ("草莓", "水果", 32, 1.0, 7.1, 0.2),
    ("蓝莓", "水果", 57, 0.7, 14.5, 0.3),
    ("西瓜", "水果", 31, 0.5, 6.8, 0.3),
    ("哈密瓜", "水果", 34, 0.5, 7.9, 0.1),
    ("猕猴桃", "水果", 61, 0.8, 14.5, 0.6),
    ("梨", "水果", 51, 0.4, 13.1, 0.2),
    ("桃", "水果", 42, 0.9, 10.9, 0.1),
    ("樱桃", "水果", 46, 1.1, 10.2, 0.2),
    ("芒果", "水果", 65, 0.6, 15.0, 0.3),
    ("菠萝", "水果", 44, 0.5, 10.8, 0.1),
    ("火龙果", "水果", 55, 1.1, 13.3, 0.2),
    ("柚子", "水果", 42, 0.8, 9.5, 0.2),
    ("柠檬", "水果", 37, 1.1, 6.2, 1.2),
    ("牛油果", "水果", 161, 2.0, 7.4, 15.3),
    ("冬枣", "水果", 105, 1.8, 27.8, 0.2),
    ("石榴", "水果", 73, 1.4, 18.7, 0.2),
    # 脂肪/坚果(20)
    ("核桃", "脂肪", 646, 14.9, 19.1, 58.8),
    ("杏仁", "脂肪", 578, 21.2, 21.7, 50.6),
    ("腰果", "脂肪", 559, 17.3, 41.6, 36.7),
    ("花生", "脂肪", 567, 25.8, 16.1, 49.2),
    ("开心果", "脂肪", 562, 20.3, 27.2, 45.3),
    ("榛子", "脂肪", 628, 14.9, 16.7, 60.8),
    ("黑芝麻", "脂肪", 559, 19.1, 24.0, 46.1),
    ("亚麻籽", "脂肪", 534, 18.3, 28.9, 42.2),
    ("奇亚籽", "脂肪", 486, 16.5, 42.1, 30.7),
    ("橄榄油", "脂肪", 884, 0.0, 0.0, 100.0),
    ("花生油", "脂肪", 884, 0.0, 0.0, 100.0),
    ("黄油", "脂肪", 717, 0.9, 0.1, 81.1),
    ("花生酱", "脂肪", 588, 25.1, 20.3, 50.4),
    ("黑巧克力(85%)", "脂肪", 592, 9.8, 22.0, 52.0),
    ("夏威夷果", "脂肪", 718, 8.0, 13.8, 75.8),
    ("南瓜子", "脂肪", 559, 30.2, 10.7, 46.1),
    ("葵花籽", "脂肪", 584, 20.8, 20.0, 52.8),
    ("椰子油", "脂肪", 862, 0.0, 0.0, 100.0),
    ("奶酪(切达)", "脂肪", 403, 24.9, 1.3, 33.1),
    ("橄榄(黑)", "脂肪", 115, 0.8, 6.3, 10.7),
]
NUTRI_MAP = {n[0]: n[2:] for n in NUTRITION}

WORKOUT_TEMPLATES = [
    ("慢跑 5km 轻松跑", 40, 1, "配速 6:30 左右,心率控制在 150 以内"),
    ("间歇跑 6x400m", 45, 3, "热身 10 分钟,组间慢走 90 秒"),
    ("力量:上肢推拉", 45, 2, "俯卧撑 / 哑铃划船 / 肩推,各 4 组"),
    ("力量:下肢", 50, 3, "深蹲 / 硬拉 / 箭步蹲,注意膝盖感受"),
    ("核心 + 拉伸", 30, 1, "平板支撑 3 组 + 全身拉伸 10 分钟"),
    ("瑜伽拉伸 30 分钟", 30, 1, "重点放松髋部与腘绳肌"),
]
HABIT_TEMPLATES = [
    ("睡前拉伸 10 分钟", 10, 1, "放松小腿与腘绳肌"),
    ("23:30 前上床", 0, 1, "保证 7 小时以上睡眠"),
    ("喝水 2L", 0, 1, "训练日加 500ml"),
]
PLAN_RATIONALES = [
    "维持上周强度,重点关注恢复",
    "完成率回升,小幅加量(单周 ≤10%)",
    "工作强度大的一周,计划已减量",
    "上周疲劳明显,本周降低强度、拆分小目标",
    "状态不错,保持节奏并增加一次轻松跑",
]
MEAL_TEMPLATES: dict[str, list[tuple[str, float]]] = {
    "breakfast": [("燕麦片(干)", 50), ("牛奶(全脂)", 250), ("鸡蛋", 55), ("全麦面包", 60), ("无糖酸奶", 150), ("香蕉", 120)],
    "lunch": [("米饭(熟)", 200), ("鸡胸肉", 150), ("西兰花", 200), ("牛里脊", 120), ("糙米饭(熟)", 200), ("菠菜", 150), ("橄榄油", 8)],
    "dinner": [("红薯(蒸)", 200), ("三文鱼", 120), ("菠菜", 150), ("北豆腐", 150), ("西兰花", 180), ("米饭(熟)", 150), ("虾仁", 120)],
    "snack": [("蓝莓", 100), ("核桃", 15), ("无糖酸奶", 150), ("苹果", 180), ("黑巧克力(85%)", 10)],
}


def gen_records(rnd: random.Random) -> list[dict]:
    start = TODAY - timedelta(days=DAYS)
    low_weeks = {10, 18}          # 两段低谷周
    weight = 71.8
    prev_hard = False
    rows = []
    for i in range(DAYS):
        d = start + timedelta(days=i)
        low = (i // 7) in low_weeks
        wd = d.weekday()
        p = {0: 0.85, 2: 0.85, 4: 0.85, 6: 0.6}.get(wd, 0.22)
        if low:
            p *= 0.35
        # 连续高强度后倾向休息
        workout = (rnd.random() >= 0.6) if prev_hard else (rnd.random() < p)
        if workout:
            title, minutes, intensity, _ = rnd.choice(WORKOUT_TEMPLATES)
            wtype = "strength" if "力量" in title or "核心" in title else "running"
            if "瑜伽" in title:
                wtype = "other"
        else:
            wtype, minutes, intensity = "rest", 0, 1

        # 体重:缓降 + 噪声;低谷周平台略回升
        drift = 0.012 if low else -0.022
        weight = max(67.0, min(73.5, weight + drift + rnd.uniform(-0.18, 0.16)))

        # 睡眠:训练日略少,低谷周更少
        sleep = 7.3 + rnd.uniform(-0.6, 0.5) - (0.25 if workout else 0) - (0.5 if low else 0)
        sleep = round(max(5.2, min(9.0, sleep)), 1)

        # 体感:高强度次日易 tired;低谷周 tired 概率升高
        r = rnd.random()
        if prev_hard and r < 0.45:
            feeling = "tired"
        elif r < (0.5 if low else 0.14):
            feeling = "tired"
        elif r < 0.72:
            feeling = "normal"
        else:
            feeling = "good"

        rows.append(
            {
                "date": d,
                "workout_type": wtype,
                "workout_minutes": minutes,
                "weight_kg": round(weight, 1),
                "sleep_hours": sleep,
                "feeling": feeling,
                "note": None,
                "source": "manual",
            }
        )
        prev_hard = workout and intensity >= 3
    return rows


def gen_plans(rnd: random.Random) -> tuple[list[dict], list[dict]]:
    """近 8 周计划 + 打卡项。返回 (plans, items)。"""
    this_monday = TODAY - timedelta(days=TODAY.weekday())
    rates = [0.85, 0.7, 0.4, 0.75, 0.9, 0.8, 0.55, 0.7]  # 每周目标完成率(有起伏)
    plans, items = [], []
    for w in range(PLAN_WEEKS - 1, -1, -1):
        week_start = this_monday - timedelta(days=7 * w)
        is_current = w == 0
        rate = rates[PLAN_WEEKS - 1 - w]
        # 每周选 3~4 个训练日
        days = sorted(rnd.sample([0, 2, 4, 6], k=rnd.choice([3, 3, 4])))
        plan_items = []
        for day in days:
            d = week_start + timedelta(days=day)
            title, minutes, intensity, detail = rnd.choice(WORKOUT_TEMPLATES)
            plan_items.append({"date": d, "kind": "workout", "title": title, "detail": detail,
                               "est_minutes": minutes, "intensity": intensity})
        # 每周 2 条习惯项
        for day, habit in zip(rnd.sample(range(7), 2), rnd.sample(HABIT_TEMPLATES, 2)):
            d = week_start + timedelta(days=day)
            plan_items.append({"date": d, "kind": "habit", "title": habit[0], "detail": habit[3],
                               "est_minutes": habit[1], "intensity": habit[2]})

        for it in plan_items:
            d = it["date"]
            if is_current and d >= TODAY:
                status, feeling, checked = "pending", None, None
            else:
                rr = rnd.random()
                status = "done" if rr < rate else ("partial" if rr < rate + 0.15 else "missed")
                feeling = None
                if status in ("done", "partial"):
                    if it["intensity"] >= 3:
                        feeling = rnd.choice([2, 3, 3, 4])
                    else:
                        feeling = rnd.choice([3, 4, 4, 5])
                    checked = datetime.combine(d, time(rnd.choice([20, 20, 21]), rnd.choice([5, 15, 30, 45])), tzinfo=timezone.utc)
            it.update({"status": status, "feeling_score": feeling, "checked_at": checked})

        workout_titles = [it["title"] for it in plan_items if it["kind"] == "workout"]
        summary = f"本周 {len(workout_titles)} 次训练:" + "、".join(workout_titles)
        plans.append({"week_start": week_start, "version": 1, "status": "active" if is_current else "archived",
                      "summary": summary, "rationale": rnd.choice(PLAN_RATIONALES)})
        items.extend(plan_items)
    return plans, items


def gen_meals(rnd: random.Random) -> list[dict]:
    rows = []
    start = TODAY - timedelta(days=DAYS)
    for i in range(DAYS):
        d = start + timedelta(days=i)
        if rnd.random() >= 0.6:      # 约 6 成天数有饮食记录
            continue
        meals_plan = [("breakfast", 0.8), ("lunch", 0.9), ("dinner", 0.8), ("snack", 0.4)]
        for meal_type, prob in meals_plan:
            if rnd.random() > prob:
                continue
            candidates = rnd.sample(MEAL_TEMPLATES[meal_type], k=rnd.choice([2, 2, 3]))
            for food, base_amount in candidates:
                amount = round(base_amount * rnd.uniform(0.7, 1.3), 0)
                kcal100, p100, c100, f100 = NUTRI_MAP[food]
                rows.append({
                    "date": d, "meal_type": meal_type, "food": food, "amount_g": amount,
                    "kcal": round(kcal100 * amount / 100, 1),
                    "protein_g": round(p100 * amount / 100, 1),
                    "carb_g": round(c100 * amount / 100, 1),
                    "fat_g": round(f100 * amount / 100, 1),
                    "source": "llm",
                })
    return rows


async def main() -> int:
    configure_logging()
    rnd = random.Random(SEED)
    sm = get_sessionmaker()
    async with sm() as session:
        # 前置:确认建表
        n_tables = (
            await session.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            )
        ).scalar_one()
        if n_tables < 14:
            print("FAIL: 表未建好,请先执行:python scripts/init_db.py")
            return 1

        # 幂等清理
        uid = (
            await session.execute(select(M.User.id).where(M.User.username == DEMO_USERNAME))
        ).scalar_one_or_none()
        if uid is not None:
            for model in (
                M.PlanItem, M.Plan, M.Meal, M.HealthRecord, M.MemoryEvent,
                M.MemorySummary, M.Report, M.Message, M.WriteAudit,
            ):
                await session.execute(delete(model).where(model.user_id == uid))
            await session.execute(delete(M.Profile).where(M.Profile.user_id == uid))
            await session.execute(delete(M.User).where(M.User.id == uid))
        await session.execute(delete(M.NutritionFood))

        # 账号 + 画像
        user = M.User(
            username=DEMO_USERNAME,
            password_hash=bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt(rounds=10)).decode(),
        )
        session.add(user)
        await session.flush()
        session.add(M.Profile(
            user_id=user.id, goal="减脂", height_cm=175.0, target_weight_kg=68.0,
            equipment=["哑铃", "跑鞋", "瑜伽垫"],
            dietary_restrictions=["乳糖不耐受(轻微)"], injuries=[],
            schedule_pref={"prefer_time": "晚间", "workout_days": [0, 2, 4, 6]},
            remind_times={"checkin": "20:00", "brief": "21:30", "weekly": "周日 21:00"},
        ))

        # 营养库
        session.add_all([
            M.NutritionFood(food=f, category=c, calories=kc, protein_g=p, carbs_g=cb, fat_g=fat)
            for f, c, kc, p, cb, fat in NUTRITION
        ])

        # 记录
        records = gen_records(rnd)
        session.add_all([M.HealthRecord(user_id=user.id, **r) for r in records])

        # 计划 + 打卡
        plans, items = gen_plans(rnd)
        plan_objs = []
        for p in plans:
            obj = M.Plan(user_id=user.id, **p)
            plan_objs.append(obj)
            session.add(obj)
        await session.flush()
        # 为 items 关联 plan_id(按周分组)
        items_by_week: dict[date, list[dict]] = {}
        for it in items:
            week_start = it["date"] - timedelta(days=it["date"].weekday())
            items_by_week.setdefault(week_start, []).append(it)
        for p_obj in plan_objs:
            for it in items_by_week.get(p_obj.week_start, []):
                session.add(M.PlanItem(
                    plan_id=p_obj.id, user_id=user.id, date=it["date"], kind=it["kind"],
                    title=it["title"], detail=it["detail"], est_minutes=it["est_minutes"],
                    intensity=it["intensity"], status=it["status"],
                    feeling_score=it["feeling_score"], checked_at=it["checked_at"],
                ))

        # 饮食
        meals = gen_meals(rnd)
        session.add_all([M.Meal(user_id=user.id, **m) for m in meals])

        # 事件记忆
        session.add_all([
            M.MemoryEvent(user_id=user.id, kind="injury", description="右膝轻微不适,减少跑跳",
                          start_date=TODAY - timedelta(days=58), end_date=TODAY - timedelta(days=50)),
            M.MemoryEvent(user_id=user.id, kind="travel", description="上海出差(会议行程紧凑)",
                          start_date=TODAY - timedelta(days=33), end_date=TODAY - timedelta(days=29)),
            M.MemoryEvent(user_id=user.id, kind="checkup", description="年度体检:血脂偏高,注意饮食",
                          start_date=TODAY - timedelta(days=14), end_date=TODAY - timedelta(days=14)),
        ])

        await session.commit()

    # 汇总打印
    async with sm() as session:
        for label, sql in (
            ("health_records", "SELECT count(*) FROM health_records"),
            ("plans", "SELECT count(*) FROM plans"),
            ("plan_items", "SELECT count(*) FROM plan_items"),
            ("meals", "SELECT count(*) FROM meals"),
            ("nutrition_foods", "SELECT count(*) FROM nutrition_foods"),
            ("memory_events", "SELECT count(*) FROM memory_events"),
        ):
            n = (await session.execute(text(sql))).scalar_one()
            print(f"  {label}: {n}")
        span = (await session.execute(text("SELECT min(date), max(date) FROM health_records"))).one()
    await dispose_engine()
    print(f"GEN DONE: records {span[0]} ~ {span[1]}; demo account {DEMO_USERNAME}/{DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
