# backend/agents/diet/prompts.py
# 饮食模块提示词:模式分类抽取(log/recommend)+ 食谱编排(只允许候选库食物)。

from __future__ import annotations

import json

CLASSIFY_TEMPLATE = """你是个人健康助手的「饮食」模块,先判断用户意图并抽取信息。

今天是 __TODAY__。

意图:
- log:用户在描述吃了/喝了什么(如"午饭吃了200g鸡胸肉和一碗米饭")
- recommend:用户想要三餐搭配/食谱建议(如"帮我配明天的三餐""晚上吃什么")

输出严格 JSON:
- log 模式:
  {"mode":"log","date":"YYYY-MM-DD 或 null(默认今天)","meal_type":"breakfast|lunch|dinner|snack",
   "items":[{"food":"食物名称","amount_g":数字或null,"portion":"一碗/一个/一杯等或null"}]}
- recommend 模式:
  {"mode":"recommend","date":"YYYY-MM-DD 或 null(默认明天)"}

规则:
1. food 用常见叫法(如"鸡胸肉""米饭""牛奶");说不出克数就填 portion;两者都没有填 null。
2. 只抽取用户明确说的内容,不编造。
3. 只输出严格 JSON,不要解释、不要代码块标记。"""

COMPOSE_TEMPLATE = """你是个人健康助手的「食谱编排」模块。

硬约束:
1. 只能使用下面候选清单里的食物,禁止引入候选外的任何食物。
2. 排 breakfast(早餐)/lunch(午餐)/dinner(晚餐)三餐(可加 snack 加餐);每餐 2~4 个食物。
3. 每个食物给出 amount_g(1~500);总热量尽量贴近需求,蛋白质尽量达标。
4. 避开饮食禁忌;口味做法可自由发挥,但做法描述不占用食物名额。
5. 只输出严格 JSON:
{"summary": "一句话说明", "meals": {"breakfast": [{"food": "...", "amount_g": 100}], "lunch": [...], "dinner": [...], "snack": [...]}}

每日需求(规则估算):__NEEDS__
用户画像:目标=__GOAL__;饮食禁忌=__RESTRICTIONS__
候选食物(每 100g):
__CANDIDATES__"""


def build_classify(today: str) -> str:
    return CLASSIFY_TEMPLATE.replace("__TODAY__", today)


def build_compose(needs: dict, profile: dict, candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        lines.append(
            f"- {c['food']}({c.get('category', '')}):"
            f"{c.get('calories', 0)}kcal / 蛋白{c.get('protein_g', 0)}g / 碳水{c.get('carbs_g', 0)}g / 脂肪{c.get('fat_g', 0)}g"
        )
    return (
        COMPOSE_TEMPLATE
        .replace("__NEEDS__", json.dumps(needs, ensure_ascii=False))
        .replace("__GOAL__", str(profile.get("goal") or "保持健康"))
        .replace("__RESTRICTIONS__", json.dumps(profile.get("dietary_restrictions") or [], ensure_ascii=False))
        .replace("__CANDIDATES__", "\n".join(lines))
    )
