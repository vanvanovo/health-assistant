# scripts/check_notify.py
# P8 验收:四类主动服务(提醒/简报/周报/预警)+ 站内信/报告 REST + 幂等复放;结束复原数据。
# 前置:网关已启动(run_server.py)。
# 用法:python scripts/check_notify.py [--keep]

import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

import httpx  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402
from backend.mcp.client import call_mcp_tool  # noqa: E402

BASE = os.environ.get("HEALTH_BASE_URL", "http://127.0.0.1:8020")
USERNAME, PASSWORD = "health-demo", "health-demo"
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
    limits = httpx.Limits(max_keepalive_connections=0, max_connections=20)
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0), trust_env=False, limits=limits) as client:
        # 0) 调度器在岗
        h = await client.get(f"{BASE}/health")
        check(h.json().get("scheduler") is True, f"调度器运行中({h.json().get('scheduler')})")

        token = (await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})).json()["access_token"]
        H = {"Authorization": f"Bearer {token}"}
        s = get_settings()

        # 1) 保证今天有 pending 项(没有则补一条验收用计划项)
        r = await client.get(f"{BASE}/api/v1/plans/current", headers=H)
        plan = r.json().get("plan") or {}
        today_items = [it for it in plan.get("items", []) if it.get("date") == TODAY.isoformat()]
        if not any(it.get("status") == "pending" for it in today_items):
            items = [
                {k: it.get(k) for k in ("date", "kind", "title", "detail", "est_minutes", "intensity")}
                for it in plan.get("items", [])
            ]
            items.append({"date": TODAY.isoformat(), "kind": "habit", "title": "验收:晚间拉伸 10 分钟", "est_minutes": 10, "intensity": 1})
            res = await call_mcp_tool(s.mcp_health_url, "save_plan", {
                "week_start": plan.get("week_start"), "items": items,
                "summary": "P8 验收补充", "rationale": "验收脚本", "idempotency_key": f"p8-{TODAY.isoformat()}-plan",
            })
            check(isinstance(res, dict) and res.get("status") == "success", "补充今日待打卡项")
        else:
            check(True, "今日已有待打卡项(跳过补充)")

        # 2) 打卡提醒 + 幂等复放
        r = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "remind"}, headers=H)
        d = r.json()
        check(r.status_code == 200 and d.get("status") == "sent", f"打卡提醒 sent(实际 {d.get('status')})")
        r2 = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "remind"}, headers=H)
        check(r2.json().get("status") == "duplicate", "提醒幂等复放 → duplicate")

        # 3) 每日简报(报告 + 站内信)
        r = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "brief"}, headers=H)
        d = r.json()
        check(r.status_code == 200 and d.get("status") == "sent" and d.get("report_id"), "每日简报 sent + 报告落库")
        r2 = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "brief"}, headers=H)
        check(r2.json().get("status") == "duplicate", "简报幂等复放 → duplicate")

        # 4) 周报
        r = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "weekly"}, headers=H)
        check(r.status_code == 200 and r.json().get("status") == "sent", "周报 sent")

        # 5) 预警:构造连续两晚低睡眠
        for off in (1, 2):
            await call_mcp_tool(s.mcp_health_url, "upsert_health_record", {
                "date": (TODAY - timedelta(days=off)).isoformat(), "sleep_hours": 5.5,
            })
        r = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "alert"}, headers=H)
        alerts = r.json().get("alerts") or []
        check(any(a.get("rule") == "sleep_debt" for a in alerts), f"低睡眠 → sleep_debt 预警(实际 {[a.get('rule') for a in alerts]})")
        r2 = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": "alert"}, headers=H)
        check(r2.json().get("status") == "none", "预警复放不重复")

        # 6) 站内信 REST:未读 / 单条已读 / 全部已读
        r = await client.get(f"{BASE}/api/v1/messages", params={"unread": True}, headers=H)
        body = r.json()
        unread_list = body.get("messages") or []
        check(body.get("unread", 0) >= 3 and len(unread_list) >= 3, f"未读站内信 {body.get('unread')} 条")
        r = await client.post(f"{BASE}/api/v1/messages/read", json={"id": unread_list[0]["id"]}, headers=H)
        check(r.json().get("unread") == body["unread"] - 1, "单条已读 → 未读数 -1")
        r = await client.post(f"{BASE}/api/v1/messages/read", json={"all": True}, headers=H)
        check(r.json().get("unread") == 0, "全部已读 → 未读数 0")

        # 7) 报告 REST
        r = await client.get(f"{BASE}/api/v1/reports", params={"type": "weekly"}, headers=H)
        check(r.status_code == 200 and r.json().get("count", 0) >= 1, "周报可查")
        r = await client.get(f"{BASE}/api/v1/reports", params={"type": "daily"}, headers=H)
        check(r.status_code == 200 and r.json().get("count", 0) >= 1, "简报可查")

    if not KEEP:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 复原演示数据 …")
        await regen()

    print(f"\nCHECK NOTIFY: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
