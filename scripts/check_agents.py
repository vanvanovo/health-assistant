# scripts/check_agents.py
# P3 验收脚本:三张 LangGraph 图真实链路验证(真 LLM + 真 MCP + 真库)。
# 前置:网关已启动(python -m uvicorn backend.main:app --port 8020)+ PG 容器健康。
# 运行:python scripts/check_agents.py [--keep]   (--keep:不重灌演示数据)

import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

from backend.agents.analyst.graph import run_analyst  # noqa: E402
from backend.agents.planner.graph import run_planner  # noqa: E402
from backend.agents.planner.rules import target_week_start  # noqa: E402
from backend.agents.recorder.graph import run_recorder  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402
from backend.mcp.client import call_mcp_tool  # noqa: E402

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
    ws = target_week_start(date.today()).isoformat()
    print(f"today={today} target_week={ws}")

    # 1) 记录:完整信息 → 落库 + 确认卡
    r1 = await run_recorder("今天慢跑 30 分钟,体重 67.9,睡了 7 小时,感觉很不错", today=today)
    check(r1["status"] == "ok" and (r1.get("card") or {}).get("type") == "record_confirm",
          "recorder 完整记录 → ok(确认卡)")
    check(r1["data"] and abs(float(r1["data"]["record"]["weight_kg"]) - 67.9) < 0.01,
          "记录体重 67.9 已落库")

    # 2) 记录:缺体重 → 追问(正常业务态)
    r2 = await run_recorder("今天跑了 5 公里", today=today)
    check(r2["status"] == "clarify" and "体重" in r2["message"], "recorder 缺体重 → 追问")

    # 3) 分析:近 30 天(真实 LLM 解读)
    r3 = await run_analyst(today=today)
    interp = ((r3.get("card") or {}).get("payload") or {}).get("interpretation") or ""
    check(r3["status"] == "ok" and len(interp) >= 10, "analyst LLM 解读非空")
    summary = ((r3.get("card") or {}).get("payload") or {}).get("summary") or {}
    check((summary.get("recorded_days") or 0) >= 25, "analyst 统计窗口 ≥25 天")

    # 4) 计划:下周(真实 LLM 生成 + 版本化保存)
    note = "帮我排下周训练计划,周三要出差"
    r4 = await run_planner(note, today=today)
    check(r4["status"] == "ok" and (r4.get("card") or {}).get("type") == "plan", "planner 生成计划 → ok")
    check(int((r4.get("data") or {}).get("version") or 0) >= 1, f"计划版本 v{(r4.get('data') or {}).get('version')}")
    items = ((r4.get("card") or {}).get("payload") or {}).get("items") or []
    check(len(items) >= 3, "计划明细 ≥3 项")
    check(all(it["date"].startswith(ws[:8]) for it in items) or all(it["date"] >= ws for it in items),
          "计划项均在目标周(日期不早于周一)")

    # 5) 计划幂等:同输入复放 → 同一计划(不产生新版本)
    r5 = await run_planner(note, today=today)
    check(r5["status"] == "ok" and (r5.get("data") or {}).get("plan_id") == (r4.get("data") or {}).get("plan_id"),
          "planner 同请求复放 → 同一计划")

    # 6) 用 MCP 工具独立复核计划已落库
    s = get_settings()
    got = await call_mcp_tool(s.mcp_health_url, "get_active_plan", {"date": ws})
    got_data = got.get("data") if isinstance(got, dict) else {}
    check(isinstance(got, dict) and got.get("status") == "success"
          and got_data.get("plan_id") == (r4.get("data") or {}).get("plan_id"), "MCP 复核:计划可查且 id 一致")
    check(len(got_data.get("items") or []) >= 3, "MCP 复核:计划明细 ≥3 项")

    # 7) 复原演示数据
    if not KEEP:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 重灌演示数据,复原验收写入 …")
        await regen()
    else:
        print("\n[restore] --keep:跳过数据复原")

    print(f"\nCHECK AGENTS: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
