# backend/core/router.py
# 意图路由:规则前置(零 Token)→ LLM 意图 JSON(可多意图 + 槽位 + 追问 + 近期对话上下文)。

from __future__ import annotations

import re
from datetime import date

from backend.agents.common import llm_json

INTENTS = {"record", "checkin", "analyze", "plan", "diet", "memory", "knowledge", "out_of_scope"}

GREETINGS = ("你好", "您好", "hi", "hello", "嗨", "在吗", "早上好", "中午好", "晚上好", "早安", "晚安")
THANKS = ("谢谢", "感谢", "多谢", "thanks", "thx", "辛苦了")
HELP = ("帮助", "能做什么", "怎么用", "你会什么", "你能做什么", "介绍一下自己")

HELP_REPLY = (
    "你好呀~我是你的个人健康助手,可以这样用:\n"
    "· 记录:「今天跑了 5 公里,体重 68.2,睡了 7 个半小时」\n"
    "· 打卡:「今天的训练完成了,有点累」\n"
    "· 看状态:「我最近一个月状态怎么样?」\n"
    "· 排计划:「下周给我排训练计划,周三要出差」"
)
THANKS_REPLY = "不客气~ 坚持记录,趋势会说话。"

SYSTEM_TEMPLATE = """你是个人健康助手的意图识别模块。今天是 __TODAY__。

可选意图(严格使用这些名字):
- record: 记录健康数据(跑步/力量训练、体重、睡眠、体感)
- checkin: 对计划项打卡(仅完成状态:"今天训练完成了/没做/做了一半")
- analyze: 查看统计/趋势/状态("最近一个月怎么样""这周睡眠如何")
- plan: 生成或调整训练计划("帮我排下周计划")
- diet: 饮食记录与推荐("午饭吃了200g鸡胸肉""帮我配明天的三餐""晚上饿了吃什么好")
- memory: 更新长期画像/偏好/禁忌,设置提醒,或记录伤病/出差/体检等事件
  ("我膝盖不好""下周一到周三出差""记住:提醒我每天 21 点打卡""目标是增肌")
- knowledge: 健康知识问答(该能力即将上线)
- out_of_scope: 与个人健康管理无关

输出严格 JSON:
{"intents": [{"name": "意图名", "query": "该意图对应的原文片段"}],
 "slots": {"days": 数字(仅 analyze,7/14/30), "status": "done|partial|missed"(仅 checkin),
           "feeling_score": 1~5(仅 checkin,用户明确说体感时)},
 "need_clarify": false, "clarify": "信息不足时的追问文案", "confidence": 0.0~1.0}

规则:
1. 一句话含多个诉求 → 输出多个 intent,保持原文顺序;但不要过度拆分:同一个诉求只用一个 intent。
   同一天的多项健康数据(运动/体重/睡眠/体感)= 同一个 record,不要拆成多个。
2. record 与 checkin 的区分:描述"今天做了什么/身体状态如何"(含体感、睡眠、体重)→ record;
   只有针对计划项表达"做了/没做/做了一半"(如"训练完成了""鸽了")→ checkin;"今天休息"属于 record(记录休息日)。
   长期偏好/禁忌/未来的事件陈述(如"以后别排深蹲跳""下周一到周三出差")→ memory,不是 record。
3. 计划/打卡请求里顺带提到的日程或状态(如"排计划,周三要出差""完成了,有点累")是请求的附带说明,
   不额外输出 memory/record;只有独立的日程陈述("下周一到周三出差")才用 memory。
4. 消息里顺带提到的体感/状态(如"有点累""状态不错")如果是打卡或计划请求的附带说明,
   不要额外输出 record——只有用户明确在告知当天健康数据时才用 record。
5. 只有完全无法处理时才 need_clarify=true。
6. slots 没有就给空对象 {}。"""


def build_system(today: str) -> str:
    return SYSTEM_TEMPLATE.replace("__TODAY__", today)


def _normalize(text: str) -> str:
    return re.sub(r"[\s,。!?!?~…、]+", "", (text or "").strip())


def prefilter(user_input: str) -> dict | None:
    """规则前置:命中返回 {"message": 直答},否则 None(零 Token)。"""
    t = _normalize(user_input)
    if not t:
        return {"message": "想记录点什么?比如「今天跑了 5 公里,体重 68.2」"}
    if len(t) <= 8 and any(k in t for k in GREETINGS):
        return {"message": HELP_REPLY}
    if len(t) <= 10 and any(k in t for k in THANKS):
        return {"message": THANKS_REPLY}
    if len(t) <= 12 and any(k in t for k in HELP):
        return {"message": HELP_REPLY}
    return None


def _clean_slots(raw) -> dict:
    slots: dict = {}
    if not isinstance(raw, dict):
        return slots
    if raw.get("days") is not None:
        try:
            slots["days"] = min(max(int(raw["days"]), 1), 180)
        except (TypeError, ValueError):
            pass
    if raw.get("status") in ("done", "partial", "missed"):
        slots["status"] = raw["status"]
    if raw.get("feeling_score") is not None:
        try:
            fs = int(raw["feeling_score"])
            if 1 <= fs <= 5:
                slots["feeling_score"] = fs
        except (TypeError, ValueError):
            pass
    return slots


def _format_history(history, limit: int = 6, width: int = 100) -> str:
    """把近期消息格式化为上下文文本(支持 LangChain 消息对象或 dict)。"""
    lines: list[str] = []
    for m in (history or [])[-limit:]:
        role_raw = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else "") or ""
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        role = "用户" if str(role_raw) in ("human", "user") else "助手"
        text = str(content or "").strip().replace("\n", " ")
        if text:
            lines.append(f"{role}: {text[:width]}")
    return "\n".join(lines)


async def route_intent(user_input: str, today: str | None = None, history=None) -> dict:
    """LLM 意图识别(可带近期对话,用于理解指代);输出经归一与白名单清洗。"""
    system = build_system(today or date.today().isoformat())
    ctx = _format_history(history)
    if ctx:
        system += "\n\n近期对话(用于理解指代;不要重复回答历史内容):\n" + ctx

    data = await llm_json.chat_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_input},
        ],
        temperature=0,
    )
    raw_intents = data.get("intents") or []
    intents: list[dict] = []
    for it in raw_intents if isinstance(raw_intents, list) else []:
        if isinstance(it, str):
            name, query = it, user_input
        elif isinstance(it, dict):
            name, query = it.get("name"), it.get("query") or user_input
        else:
            continue
        if name not in INTENTS:
            name = "out_of_scope"
        intents.append({"name": name, "query": str(query)})
    if not intents:
        intents = [{"name": "out_of_scope", "query": user_input}]

    # 同意图合并:同一 handler 多次出现 → 合并为一个(原文片段用「、」拼接)
    merged: dict[str, str] = {}
    order: list[str] = []
    for it in intents:
        name, q = it["name"], (it.get("query") or user_input)
        if name in merged:
            if str(q) not in merged[name]:
                merged[name] = f"{merged[name]}、{q}"
        else:
            merged[name] = str(q)
            order.append(name)
    intents = [{"name": n, "query": merged[n]} for n in order]

    try:
        confidence = float(data.get("confidence", 0.8))
    except (TypeError, ValueError):
        confidence = 0.8

    return {
        "intents": intents,
        "slots": _clean_slots(data.get("slots")),
        "need_clarify": bool(data.get("need_clarify")),
        "clarify": str(data.get("clarify") or "").strip(),
        "confidence": max(0.0, min(confidence, 1.0)),
    }
