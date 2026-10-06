# backend/agents/diet/nodes.py
# 饮食图节点:
#   classify →(log)match → calc → save → format_log
#           →(recommend)needs → candidates → compose → format_recommend

from __future__ import annotations

from datetime import date, timedelta

from backend.agents.common import llm_json, tools
from backend.agents.common.result import agent_result
from backend.agents.common.utils import short_hash

from . import prompts
from .rules import check_plan_totals, compute_daily_needs, resolve_amount

MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
MEAL_CN = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}
CANDIDATE_PLAN = (("蛋白质", 10), ("碳水", 8), ("蔬菜", 8), ("水果", 5), ("脂肪", 5))

# 常用食材优先(保证鸡蛋/米饭这类家常食材一定在候选里,再按蛋白密度补充)
STAPLE_PRIORITY: dict[str, list[str]] = {
    "蛋白质": ["鸡蛋", "鸡胸肉", "牛里脊", "虾仁", "北豆腐", "无糖酸奶", "牛奶(全脂)", "三文鱼"],
    "碳水": ["米饭(熟)", "燕麦片(干)", "全麦面包", "红薯(蒸)", "玉米(煮)", "意大利面(熟)"],
    "蔬菜": ["西兰花", "菠菜", "生菜", "番茄", "黄瓜", "胡萝卜"],
    "水果": ["苹果", "香蕉", "蓝莓", "橙子"],
    "脂肪": ["橄榄油", "核桃", "花生酱", "黑巧克力(85%)"],
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(s):
    if isinstance(s, str) and s.strip():
        try:
            return date.fromisoformat(s.strip()[:10])
        except ValueError:
            return None
    return None


# ── 公共 ─────────────────────────────────────────────────────
async def classify_node(state) -> dict:
    data = await llm_json.chat_json(
        [
            {"role": "system", "content": prompts.build_classify(state["today"])},
            {"role": "user", "content": state["user_input"]},
        ],
        temperature=0,
    )
    mode = data.get("mode") if data.get("mode") in ("log", "recommend") else None
    if mode is None:  # 兜底:按关键词判
        mode = "log" if any(k in state["user_input"] for k in ("吃", "喝")) else "recommend"
    return {"mode": mode, "parse": data if isinstance(data, dict) else {}}


def route_after_classify(state) -> str:
    return state.get("mode", "recommend")


# ── log 分支:记录估算 ─────────────────────────────────────────
async def match_node(state) -> dict:
    parse = state.get("parse") or {}
    today = date.fromisoformat(state["today"])
    d = _parse_date(parse.get("date")) or today
    if d > today:
        d = today
    meal_type = parse.get("meal_type") if parse.get("meal_type") in MEAL_TYPES else "lunch"

    matched: list[dict] = []
    errors: list[dict] = []
    raw_items = parse.get("items") if isinstance(parse.get("items"), list) else []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        food = str(it.get("food") or "").strip()
        if not food:
            continue
        try:
            amount = resolve_amount(food, it.get("portion"), it.get("amount_g"))
        except ValueError as e:
            errors.append({"food": food, "error": str(e)})
            continue
        res = await tools.call_tool("search_food", {"keyword": food, "limit": 5})
        foods = (tools.tool_data(res) or {}).get("foods") or []
        cands = [f for f in foods if f["food"] == food] \
            or [f for f in foods if f["food"].startswith(food)] \
            or [f for f in foods if food in f["food"]] \
            or foods
        picked = cands[0] if cands else None
        if not picked:
            errors.append({"food": food, "error": "营养库中未找到该食物"})
            continue
        matched.append({"food": picked["food"], "amount_g": amount, "ref": picked})

    return {"date": d.isoformat(), "meal_type": meal_type, "matched": matched, "errors": errors}


async def calc_node(state) -> dict:
    items: list[dict] = []
    for m in state.get("matched") or []:
        ref, g = m["ref"], m["amount_g"]
        factor = g / 100.0
        items.append({
            "food": m["food"],
            "amount_g": g,
            "kcal": round((ref.get("calories") or 0) * factor, 1),
            "protein_g": round((ref.get("protein_g") or 0) * factor, 1),
            "carb_g": round((ref.get("carbs_g") or 0) * factor, 1),
            "fat_g": round((ref.get("fat_g") or 0) * factor, 1),
        })
    totals = {k: round(sum(i[k] for i in items), 1) for k in ("kcal", "protein_g", "carb_g", "fat_g")}
    return {"items": items, "totals": totals}


async def save_node(state) -> dict:
    items = state.get("items") or []
    if not items:
        return {"saved": {}}
    key = f"diet-{state['date']}-{state['meal_type']}-{short_hash(state['user_input'])}"
    res = await tools.call_tool(
        "add_meal",
        {
            "date": state["date"], "meal_type": state["meal_type"],
            "items": [
                {k: i[k] for k in ("food", "amount_g", "kcal", "protein_g", "carb_g", "fat_g")}
                for i in items
            ],
            "source": "llm", "idempotency_key": key,
        },
    )
    return {"saved": res if isinstance(res, dict) else {}}


async def format_log_node(state) -> dict:
    items = state.get("items") or []
    errors = state.get("errors") or []
    if not items:
        detail = "、".join(f"{e['food']}({e['error']})" for e in errors) or "没有识别到可记录的内容"
        return {"result": agent_result("diet", "failed", f"这条没记上:{detail}")}

    saved = state.get("saved") or {}
    if saved.get("status") not in ("success", "duplicate"):
        return {
            "result": agent_result(
                "diet", "failed", f"饮食写入失败:{saved.get('message', '未知错误')}", degraded=True
            )
        }

    day = tools.tool_data(await tools.call_tool("get_day_intake", {"date": state["date"]}), {}) or {}
    tops = day.get("total") or {}
    detail = "、".join(f"{i['food']} {int(i['amount_g'])}g" for i in items)
    message = (
        f"已记录{MEAL_CN[state['meal_type']]}:{detail},约 {state['totals']['kcal']:.0f} kcal"
        f"(蛋白 {state['totals']['protein_g']:.0f}g,估算值,可修正)。"
    )
    if tops:
        message += f" 今日累计约 {tops.get('kcal', 0):.0f} kcal。"
    if errors:
        message += " 未识别:" + "、".join(f"{e['food']}({e['error']})" for e in errors) + "。"

    card = {
        "type": "diet",
        "payload": {
            "mode": "log", "date": state["date"], "meal_type": state["meal_type"],
            "items": items, "totals": state["totals"], "day_totals": tops, "errors": errors,
            "note": "克数与热量为估算值;如需修正直接再说一句",
        },
    }
    return {"result": agent_result("diet", "ok", message, card=card, data={"items": items, "totals": state["totals"]})}


# ── recommend 分支:食谱推荐 ──────────────────────────────────
async def needs_node(state) -> dict:
    today = date.fromisoformat(state["today"])
    parse = state.get("parse") or {}
    d = _parse_date(parse.get("date")) or (today + timedelta(days=1))

    profile = tools.tool_data(await tools.call_tool("get_profile", {}), {}) or {}
    rec_res = tools.tool_data(
        await tools.call_tool(
            "query_records",
            {"date_from": (today - timedelta(days=6)).isoformat(), "date_to": today.isoformat(), "limit": 7},
        ),
        {},
    ) or {}
    recs = rec_res.get("records") or []
    weight = next((r["weight_kg"] for r in reversed(recs) if r.get("weight_kg")), None) \
        or profile.get("target_weight_kg") or 65.0
    summary = tools.tool_data(
        await tools.call_tool(
            "get_range_summary",
            {"date_from": (today - timedelta(days=6)).isoformat(), "date_to": today.isoformat()},
        ),
        {},
    ) or {}
    training_day = ((summary.get("workout") or {}).get("days") or 0) >= 3
    needs = compute_daily_needs(weight, profile.get("goal"), training_day)
    return {"date": d.isoformat(), "profile": profile, "needs": needs}


async def candidates_node(state) -> dict:
    """候选 = 常用食材优先 + 蛋白密度补充(保证家常食材在列,同时保留高性价比选择)。"""
    pool: dict[str, dict] = {}
    for category, limit in CANDIDATE_PLAN:
        res = await tools.call_tool("search_food", {"category": category, "limit": 30})
        foods = (tools.tool_data(res) or {}).get("foods") or []
        by_name = {f["food"]: f for f in foods}
        chosen: list[dict] = []
        seen: set[str] = set()
        for name in STAPLE_PRIORITY.get(category, []):
            if name in by_name:
                chosen.append(by_name[name])
                seen.add(name)
        for f in foods:   # 已按蛋白密度降序
            if len(chosen) >= limit:
                break
            if f["food"] not in seen:
                chosen.append(f)
                seen.add(f["food"])
        for f in chosen:
            pool[f["food"]] = f
    if len(pool) < 8:
        raise RuntimeError("营养库候选不足,请检查营养库数据")
    return {"candidates": list(pool.values())}


async def compose_node(state) -> dict:
    """LLM 只从候选排餐;本地校验候选范围 + 热量带 + 蛋白下限,不通过重排 1 次。"""
    needs = state["needs"]
    cands = state["candidates"]
    refs = {c["food"]: c for c in cands}
    messages = [
        {"role": "system", "content": prompts.build_compose(needs, state.get("profile") or {}, cands)},
        {"role": "user", "content": state["user_input"]},
    ]
    last_issues: list[str] = []
    for _ in range(3):
        data = await llm_json.chat_json(messages, temperature=0.3)
        meals_raw = data.get("meals") if isinstance(data.get("meals"), dict) else {}
        issues: list[str] = []
        meals: dict[str, list[dict]] = {}
        totals = {"kcal": 0.0, "protein_g": 0.0, "carb_g": 0.0, "fat_g": 0.0}
        for slot in ("breakfast", "lunch", "dinner", "snack"):
            slot_items: list[dict] = []
            for it in meals_raw.get(slot) or []:
                if not isinstance(it, dict):
                    continue
                food = str(it.get("food") or "").strip()
                if food not in refs:
                    issues.append(f"候选外食物:{food}")
                    continue
                amount = _num(it.get("amount_g"))
                if amount is None or not (0 < amount <= 500):
                    issues.append(f"份量不合法:{food}")
                    continue
                ref = refs[food]
                factor = amount / 100.0
                item = {
                    "food": food, "amount_g": round(amount, 1),
                    "kcal": round((ref.get("calories") or 0) * factor, 1),
                    "protein_g": round((ref.get("protein_g") or 0) * factor, 1),
                    "carb_g": round((ref.get("carbs_g") or 0) * factor, 1),
                    "fat_g": round((ref.get("fat_g") or 0) * factor, 1),
                }
                slot_items.append(item)
                for k in totals:
                    totals[k] = round(totals[k] + item[k], 1)
            if slot_items:
                meals[slot] = slot_items

        if not meals:
            issues = issues or ["没有生成任何餐次"]
        if not issues:
            issues = check_plan_totals(totals, needs)
        if not issues:
            return {
                "meals": meals,
                "totals": totals,
                "summary": str(data.get("summary") or "")[:200],
            }
        last_issues = issues
        messages = messages + [
            {"role": "user", "content": "上一版有问题:" + ";".join(issues)
             + "。请修正后重新输出严格 JSON。再次强调:所有 food 必须（且只能）从以下列表中选择:" 
             + "、".join(sorted(refs))}
        ]
    raise ValueError("食谱校验未通过:" + ";".join(last_issues))


async def format_recommend_node(state) -> dict:
    needs = state["needs"]
    meals = state["meals"]
    totals = state["totals"]
    message = (
        f"{state['date']} 的食谱(目标「{needs['goal']}」,每日需求约 {needs['kcal']} kcal / 蛋白 {needs['protein_g']}g):"
        f"本食谱约 {totals['kcal']:.0f} kcal / 蛋白 {totals['protein_g']:.0f}g。{state.get('summary') or ''}"
    )
    card = {
        "type": "diet",
        "payload": {
            "mode": "recommend", "date": state["date"], "needs": needs,
            "meals": meals, "totals": totals, "summary": state.get("summary"),
            "note": "需求为规则估算;食谱由 LLM 从候选库编排,热量为营养库换算值",
        },
    }
    return {
        "result": agent_result(
            "diet", "ok", message,
            card=card, data={"needs": needs, "totals": totals, "meals": meals},
        )
    }
