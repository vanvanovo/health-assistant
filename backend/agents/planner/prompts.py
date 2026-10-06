# backend/agents/planner/prompts.py
# 计划生成提示词:硬约束"只引用给定数据与候选动作";输出严格 JSON。

from __future__ import annotations

import json
from datetime import date, timedelta

from backend.agents.common.utils import weekday_cn

LEVEL_HINT = {
    "up": "上周完成率高且状态好 → 较上周小幅加量(单周增幅 ≤10%)",
    "keep": "保持上周强度与结构",
    "down": "降低强度、拆分小目标(强度不超过 2 的项要占多数)",
}

CANDIDATES = [
    "慢跑 5km 轻松跑", "间歇跑 6x400m", "快走 40 分钟", "力量:上肢推拉",
    "力量:下肢", "核心 + 拉伸", "瑜伽拉伸 30 分钟", "睡前拉伸 10 分钟",
    "23:30 前上床", "喝水 2L", "晚餐少油少糖",
]

SYSTEM_TEMPLATE = """你是个人健康助手的「周计划生成」模块。基于给定的统计数据、画像与约束,生成目标周的计划。

硬约束(必须遵守):
1. 只能使用下面给定的数据和候选动作;禁止编造任何统计数字、身体数据或事件。
2. 强度档:__LEVEL_HINT__
3. 目标周从 __WEEK_START__ 开始,共 7 天:__WEEK_DATES__。
4. 训练(workout)从这些天里选(0=周一):__WORKOUT_DAYS__;每周 workout 3~4 次,每天最多 1 个 workout 项。
5. __LIGHT_NOTE__
6. __AVOID_NOTE__
7. 除了训练,可加 2~3 个 habit(习惯)项与至多 2 条 diet(饮食)提示项。
8. intensity 取 1(轻)/2(中)/3(高);强度档为 down 时,workout 的 intensity 不得为 3。
9. rationale 必须引用给定统计(完成率/体感/事件等)说明为什么这样排,1~2 句。
10. 只输出严格 JSON,不要解释、不要代码块标记。

输出格式:
{"summary": "一句话概要", "rationale": "调档依据", "items": [
  {"date": "YYYY-MM-DD", "kind": "workout|habit|diet", "title": "动作名", "detail": "要点", "est_minutes": 30, "intensity": 1}
]}

候选动作(只能从中选择或合理裁剪):__CANDIDATES__"""


def build_system(
    week_start: date, constraints: dict, summary: dict, profile: dict, events: list[dict]
) -> str:
    week_dates = "、".join(
        f"{(week_start + timedelta(days=i)).isoformat()}({weekday_cn(week_start + timedelta(days=i))})"
        for i in range(7)
    )
    light = constraints.get("light_dates") or {}
    light_note = (
        "这些日期安排轻量内容(拉伸/散步/恢复),不要排高强度:" + "、".join(light.keys())
        if light else "无特殊轻量日约束"
    )
    avoid = constraints.get("avoid") or []
    avoid_note = "规避项:" + "、".join(avoid) if avoid else "无伤病规避项"

    facts = {
        "近30天统计": summary,
        "画像": profile,
        "有效事件": events,
        "调档依据": constraints.get("reasons"),
    }
    return (
        SYSTEM_TEMPLATE
        .replace("__LEVEL_HINT__", LEVEL_HINT.get(constraints.get("level", "keep"), LEVEL_HINT["keep"]))
        .replace("__WEEK_START__", week_start.isoformat())
        .replace("__WEEK_DATES__", week_dates)
        .replace("__WORKOUT_DAYS__", str(constraints.get("workout_days")))
        .replace("__LIGHT_NOTE__", light_note)
        .replace("__AVOID_NOTE__", avoid_note)
        .replace("__CANDIDATES__", "、".join(CANDIDATES))
        + "\n\n给定数据:\n" + json.dumps(facts, ensure_ascii=False, default=str)
    )
