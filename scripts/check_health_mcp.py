# scripts/check_health_mcp.py
# P2 验收脚本:连接运行中的网关,列出 MCP 全部工具并逐一调用验证;结束后重灌演示数据。
# 前置:网关已启动(python -m uvicorn backend.main:app --port 8020)
# 运行:python scripts/check_health_mcp.py [--keep]   (--keep:不重灌演示数据)

import os
import sys
import time
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

import httpx  # noqa: E402

from backend.core.logger import configure_logging  # noqa: E402
from backend.mcp.client import call_mcp_tool, list_mcp_tools  # noqa: E402

BASE = os.environ.get("MCP_HEALTH_URL", "http://localhost:8020/mcp/health")
RUN = time.strftime("%m%d%H%M%S")
TODAY = date.today()
KEEP = "--keep" in sys.argv

_ok, _fail = 0, 0


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
    print(f"MCP Server: {BASE}")

    # 前置:确保从干净基线开始(上一轮验收的写入不残留)
    if not KEEP:
        from gen_demo_data import main as regen  # noqa: E402
        print("[restore] 重灌演示数据,确保验收从干净基线开始 …")
        await regen()

    # 0) 工具清单
    tools = await list_mcp_tools(BASE)
    names = sorted(t["name"] for t in tools)
    print(f"tools({len(names)}): {names}")
    check(len(names) == 15, "工具数 = 15")
    for required in ("upsert_health_record", "get_range_summary", "save_plan", "upsert_checkin",
                     "search_food", "add_meal", "update_profile", "list_active_events"):
        check(required in names, f"工具存在:{required}")

    # 1) upsert 今日记录 + 幂等复放 + 非法值拦截
    rec_args = {
        "date": TODAY.isoformat(), "workout_type": "running", "workout_minutes": 30,
        "weight_kg": 68.0, "sleep_hours": 7.5, "feeling": "good",
        "idempotency_key": f"p2-{RUN}-rec",
    }
    r1 = await call_mcp_tool(BASE, "upsert_health_record", rec_args)
    check(r1["status"] == "success" and r1["data"]["created"] is True, "upsert 新建今日记录")
    r2 = await call_mcp_tool(BASE, "upsert_health_record", rec_args)
    check(r2["status"] == "duplicate" and r2["data"]["record"]["id"] == r1["data"]["record"]["id"],
          "同幂等键复放 → duplicate 且返回原记录")
    r3 = await call_mcp_tool(BASE, "upsert_health_record", {"date": TODAY.isoformat(), "weight_kg": 999})
    check(r3["status"] == "invalid", "非法体重(999)被范围校验拦截")
    r3b = await call_mcp_tool(BASE, "upsert_health_record", {"date": (TODAY + timedelta(days=1)).isoformat()})
    check(r3b["status"] == "invalid", "未来日期被拦截")

    # 2) query_records
    r4 = await call_mcp_tool(BASE, "query_records", {
        "date_from": (TODAY - timedelta(days=7)).isoformat(), "date_to": TODAY.isoformat(),
    })
    check(r4["status"] == "success" and any(
        x["date"] == TODAY.isoformat() and x["weight_kg"] == 68.0 for x in r4["data"]["records"]
    ), "query_records 能查到今日新记录")

    # 3) get_range_summary(近 30 天)
    r5 = await call_mcp_tool(BASE, "get_range_summary", {
        "date_from": (TODAY - timedelta(days=29)).isoformat(), "date_to": TODAY.isoformat(),
    })
    d5 = r5["data"]
    check(r5["status"] == "success" and d5["workout"]["days"] >= 3 and d5["weight"]["points"] >= 25,
          "get_range_summary 统计口径(训练/体重)")

    # 4) import_records:2 有效 + 1 非法
    r6 = await call_mcp_tool(BASE, "import_records", {
        "rows": [
            {"date": (TODAY - timedelta(days=181)).isoformat(), "weight_kg": 72.0, "sleep_hours": 7.0},
            {"date": (TODAY - timedelta(days=182)).isoformat(), "workout_type": "running", "workout_minutes": 30},
            {"date": "not-a-date"},
        ],
        "idempotency_key": f"p2-{RUN}-imp",
    })
    check(r6["status"] == "success" and r6["data"]["imported"] == 2 and r6["data"]["invalid"] == 1,
          "import_records:2 条导入 + 1 条拦截")

    # 5) save_plan(两周前)+ 幂等 + 版本递增
    ws = TODAY - timedelta(days=TODAY.weekday()) - timedelta(days=14)
    plan_args = {
        "week_start": ws.isoformat(),
        "items": [
            {"date": ws.isoformat(), "kind": "workout", "title": "验收:慢跑 20 分钟", "est_minutes": 20, "intensity": 1},
            {"date": (ws + timedelta(days=2)).isoformat(), "kind": "habit", "title": "验收:睡前拉伸"},
        ],
        "summary": "P2 验收计划",
        "rationale": "验收脚本生成",
        "idempotency_key": f"p2-{RUN}-plan",
    }
    r7 = await call_mcp_tool(BASE, "save_plan", plan_args)
    check(r7["status"] == "success" and r7["data"]["version"] >= 2, "save_plan 生成新版本(旧版归档)")
    r8 = await call_mcp_tool(BASE, "save_plan", plan_args)
    check(r8["status"] == "duplicate" and r8["plan_id"] == r7["data"]["plan_id"], "save_plan 幂等复放")
    item_id = r7["data"]["items"][0]["id"]

    # 6) upsert_checkin:计划内 + 计划外自由打卡 + 幂等
    r9 = await call_mcp_tool(BASE, "upsert_checkin", {"plan_item_id": item_id, "status": "done", "feeling_score": 4})
    check(r9["status"] == "success" and r9["data"]["item"]["status"] == "done"
          and r9["data"]["item"]["feeling_score"] == 4, "计划内打卡(状态+体感)")
    r10 = await call_mcp_tool(BASE, "upsert_checkin", {
        "date": TODAY.isoformat(), "kind": "habit", "title": "验收:喝水 2L", "status": "done",
        "idempotency_key": f"p2-{RUN}-ck",
    })
    check(r10["status"] == "success" and r10["data"]["ad_hoc"] is True, "计划外自由打卡")
    r11 = await call_mcp_tool(BASE, "upsert_checkin", {
        "date": TODAY.isoformat(), "kind": "habit", "title": "验收:喝水 2L", "status": "done",
        "idempotency_key": f"p2-{RUN}-ck",
    })
    check(r11["status"] == "duplicate" and r11["plan_item_id"] == r10["data"]["item"]["id"], "自由打卡幂等复放")

    # 7) get_active_plan + get_plan_progress
    r12 = await call_mcp_tool(BASE, "get_active_plan", {"date": ws.isoformat()})
    check(r12["status"] == "success" and r12["data"]["version"] == r7["data"]["version"]
          and len(r12["data"]["items"]) == 2, "get_active_plan 返回当前生效版本")
    r13 = await call_mcp_tool(BASE, "get_plan_progress", {"week_start": ws.isoformat()})
    check(r13["status"] == "success" and r13["data"]["progress"]["done"] >= 1,
          "get_plan_progress 完成率可算")

    # 8) search_food(蛋白密度排序)
    r14 = await call_mcp_tool(BASE, "search_food", {"category": "蛋白质", "limit": 5})
    foods = r14["data"]["foods"]
    densities = [f["protein_density"] for f in foods]
    check(r14["status"] == "success" and len(foods) == 5
          and all(densities[i] >= densities[i + 1] for i in range(len(densities) - 1)),
          "search_food 按蛋白密度降序")

    # 9) add_meal(自动换算)+ 幂等 + get_day_intake
    r15 = await call_mcp_tool(BASE, "add_meal", {
        "date": TODAY.isoformat(), "meal_type": "lunch",
        "items": [{"food": "鸡胸肉", "amount_g": 150}, {"food": "米饭(熟)", "amount_g": 200}],
        "idempotency_key": f"p2-{RUN}-meal",
    })
    check(r15["status"] == "success" and r15["data"]["inserted"] == 2 and r15["data"]["totals"]["kcal"] > 300,
          "add_meal 按营养库自动换算热量")
    r16 = await call_mcp_tool(BASE, "add_meal", {
        "date": TODAY.isoformat(), "meal_type": "lunch",
        "items": [{"food": "鸡胸肉", "amount_g": 150}],
        "idempotency_key": f"p2-{RUN}-meal",
    })
    check(r16["status"] == "duplicate", "add_meal 幂等复放")
    r17 = await call_mcp_tool(BASE, "get_day_intake", {"date": TODAY.isoformat()})
    check(r17["status"] == "success" and r17["data"]["total"]["kcal"] >= r15["data"]["totals"]["kcal"],
          "get_day_intake 当日汇总")

    # 10) 画像 + 事件记忆
    r18 = await call_mcp_tool(BASE, "get_profile", {})
    check(r18["status"] == "success" and r18["data"]["goal"] == "减脂", "get_profile 返回画像")
    r19 = await call_mcp_tool(BASE, "update_profile", {"patch": {"goal": "保持健康"}})
    check(r19["status"] == "success" and r19["data"]["goal"] == "保持健康", "update_profile 更新白名单字段")
    r19b = await call_mcp_tool(BASE, "update_profile", {"patch": {"hack_field": 1}})
    check(r19b["status"] == "invalid", "update_profile 拒绝白名单外字段")
    r20 = await call_mcp_tool(BASE, "add_memory_event", {
        "kind": "travel", "description": "P2 验收:临时出差",
        "start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=2)).isoformat(),
        "idempotency_key": f"p2-{RUN}-evt",
    })
    check(r20["status"] == "success", "add_memory_event 写入成功")
    r21 = await call_mcp_tool(BASE, "list_active_events", {"date": TODAY.isoformat()})
    check(r21["status"] == "success" and any(e["id"] == r20["data"]["event_id"] for e in r21["data"]["events"]),
          "list_active_events 包含新事件")
    r22 = await call_mcp_tool(BASE, "list_active_events", {"date": (TODAY + timedelta(days=30)).isoformat()})
    check(all(e["kind"] != "travel" or e["id"] != r20["data"]["event_id"] for e in r22["data"]["events"]),
          "事件过期后自动失效")

    # 11) X-MCP-Key 鉴权
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        no_key = await client.post(f"{BASE}/mcp", json=payload, headers={"Accept": "application/json"})
        bad_key = await client.post(f"{BASE}/mcp", json=payload,
                                    headers={"Accept": "application/json", "X-MCP-Key": "wrong-key"})
    check(no_key.status_code == 401, f"无 X-MCP-Key → 401(实际 {no_key.status_code})")
    check(bad_key.status_code == 401, f"错误 X-MCP-Key → 401(实际 {bad_key.status_code})")

    # 12) 复原演示数据
    if not KEEP:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 重灌演示数据,复原验收产生的写入 …")
        await regen()
    else:
        print("\n[restore] --keep:跳过数据复原")

    print(f"\nCHECK HEALTH MCP: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
