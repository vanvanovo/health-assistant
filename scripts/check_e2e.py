# scripts/check_e2e.py
# P4 端到端验收:登录 → SSE 对话场景(1-5)→ 看板/计划/打卡 REST → 401 → 复原数据。
# 前置:网关已启动(--port 8020)。
# 用法:python scripts/check_e2e.py [--keep]

import json
import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

import httpx  # noqa: E402

from backend.core.logger import configure_logging  # noqa: E402

BASE = os.environ.get("HEALTH_BASE_URL", "http://127.0.0.1:8020")
USERNAME, PASSWORD = "health-demo", "health-demo"
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


def _parse_part(part: str):
    name, data_raw = None, ""
    for line in part.split("\n"):
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data_raw += line[5:].strip()
    if not name:
        return None
    try:
        return {"event": name, "data": json.loads(data_raw)}
    except (json.JSONDecodeError, TypeError):
        return {"event": name, "data": data_raw}


async def sse(client: httpx.AsyncClient, token: str, message: str) -> list[dict]:
    events: list[dict] = []
    async with client.stream(
        "POST", f"{BASE}/api/v1/chat/stream",
        json={"message": message},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"SSE HTTP {resp.status_code}")
        buf = ""
        async for chunk in resp.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                ev = _parse_part(part)
                if ev:
                    events.append(ev)
    return events


def has(events, name):
    return [e for e in events if e["event"] == name]


def text_of(events):
    return "".join(e["data"]["text"] for e in has(events, "token"))


async def main() -> int:
    configure_logging()
    timeout = httpx.Timeout(240.0, connect=10.0)
    # 禁用 keep-alive:SSE 流结束后服务端可能关闭连接,复用旧连接会偶发 ReadError(实测)
    limits = httpx.Limits(max_keepalive_connections=0, max_connections=20)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, limits=limits) as client:
        # 0) 未登录 → 401
        r = await client.post(f"{BASE}/api/v1/chat/stream", json={"message": "hi"})
        check(r.status_code == 401, "未带 token → 401")

        # 1) 登录
        r = await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": "wrong"})
        check(r.status_code == 401, "错误密码 → 401")
        r = await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        token = r.json().get("access_token") if r.status_code == 200 else None
        check(bool(token), "登录成功拿到 token")
        H = {"Authorization": f"Bearer {token}"}
        h = await client.get(f"{BASE}/health")
        check(h.json().get("memory") in ("postgres", "memory"), f"记忆层就绪({h.json().get('memory')})")

        # 2) 场景 1:一句话记录
        evs = await sse(client, token, "今天慢跑 30 分钟,体重 68.1,睡了 7 小时,感觉不错")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["record"]], "场景1 routing=record")
        check(any(c["data"]["type"] == "record_confirm" for c in has(evs, "card")), "场景1 记录卡")
        check(bool(text_of(evs)) and evs[-1]["event"] == "done", "场景1 消息流 + done")
        check("elapsed_ms" in has(evs, "meta")[0]["data"], "场景1 meta 有耗时")

        # 3) 场景 2:规则前置(零 Token)
        evs = await sse(client, token, "你好")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["rule"]], "场景2 规则前置")
        check("个人健康助手" in text_of(evs), "场景2 帮助文案直答")

        # 4) 场景 3:统计
        evs = await sse(client, token, "我最近一个月状态怎么样?")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["analyze"]], "场景3 routing=analyze")
        check(any(c["data"]["type"] == "stats" for c in has(evs, "card")), "场景3 统计卡")
        check(len(text_of(evs)) >= 10, "场景3 LLM 解读非空")

        # 5) 场景 4:计划
        evs = await sse(client, token, "下周给我排训练计划,周三要出差")
        routed4 = [e["data"]["intents"] for e in has(evs, "routing")]
        check(bool(routed4) and "plan" in routed4[0], f"场景4 routing 含 plan({routed4[0] if routed4 else None})")
        check(any(c["data"]["type"] == "plan" for c in has(evs, "card")), "场景4 计划卡")

        # 6) 场景 5:打卡
        evs = await sse(client, token, "今天的训练完成了,有点累")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["checkin"]], "场景5 routing=checkin")
        check("打卡" in text_of(evs), "场景5 打卡回复")

        # 6.5) 场景 6/7:饮食(记录估算 + 食谱推荐)
        evs = await sse(client, token, "午饭吃了200g鸡胸肉和一碗米饭")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["diet"]], "场景6 routing=diet")
        diet_cards = [c for c in has(evs, "card") if c["data"]["type"] == "diet"]
        check(bool(diet_cards) and diet_cards[0]["data"]["payload"].get("mode") == "log", "场景6 饮食卡(log)")
        evs = await sse(client, token, "帮我配明天的三餐")
        reco_cards = [
            c for c in has(evs, "card")
            if c["data"]["type"] == "diet" and c["data"]["payload"].get("mode") == "recommend"
        ]
        check(bool(reco_cards), "场景7 食谱卡(recommend)")

        # 6.8) 场景 8:长期记忆(返回待确认卡,不直接落库)
        evs = await sse(client, token, "我膝盖不好,以后别给我排深蹲跳")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["memory"]], "场景8 routing=memory")
        pcards = [c for c in has(evs, "card") if c["data"]["type"] == "profile_update"]
        check(bool(pcards) and pcards[0]["data"]["payload"].get("token"), "场景8 记忆待确认卡")

        # 6.9) 场景 9:知识问答(带来源,或明确降级);场景 10:安全边界
        evs = await sse(client, token, "晚上睡不好怎么办?")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["knowledge"]], "场景9 routing=knowledge")
        src_cards = [c for c in has(evs, "card") if c["data"]["type"] == "sources"]
        meta9 = has(evs, "meta")[0]["data"]
        check(bool(src_cards) or meta9.get("degraded") is True, "场景9 回答带来源(或明确降级)")
        evs = await sse(client, token, "我胸痛应该吃什么药")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["safety"]], "场景10 高危拦截")
        check("120" in text_of(evs) or "就医" in text_of(evs), "场景10 就医引导")
        check(has(evs, "meta")[0]["data"].get("safety", {}).get("level") == "high", "场景10 meta.safety=high")

        # 7) 看板 REST
        r = await client.get(f"{BASE}/api/v1/dashboard/overview", headers=H)
        check(r.status_code == 200 and "workout_7d" in r.json(), "dashboard/overview 结构正确")
        r = await client.get(
            f"{BASE}/api/v1/dashboard/trends",
            params={"from": (date.today() - timedelta(days=29)).isoformat(), "to": date.today().isoformat()},
            headers=H,
        )
        check(r.status_code == 200 and len(r.json().get("series", [])) >= 25, "dashboard/trends ≥25 天序列")
        r = await client.get(f"{BASE}/api/v1/dashboard/heatmap", params={"days": 90}, headers=H)
        check(r.status_code == 200 and len(r.json().get("days", [])) >= 80, "dashboard/heatmap ≥80 天数据")
        r = await client.get(f"{BASE}/api/v1/dashboard/radar", params={"weeks": 4}, headers=H)
        check(
            r.status_code == 200
            and set(r.json().get("scores", {})) == {"sport", "sleep", "diet", "recovery"},
            "dashboard/radar 四维评分",
        )

        # 7.5) 主动服务:手动触发四类任务 + 站内信/报告 REST
        for job in ("remind", "brief", "weekly", "alert"):
            r = await client.post(f"{BASE}/api/v1/jobs/run", json={"job": job}, headers=H)
            check(r.status_code == 200, f"jobs/run {job} 200")
        r = await client.get(f"{BASE}/api/v1/messages", headers=H)
        check(r.status_code == 200 and r.json().get("count", 0) >= 1, "messages 有数据")
        r = await client.get(f"{BASE}/api/v1/reports", headers=H)
        check(r.status_code == 200 and r.json().get("count", 0) >= 1, "reports 有数据")

        # 8) 计划查询 + 表单打卡
        r = await client.get(f"{BASE}/api/v1/plans/current", headers=H)
        data = r.json()
        check(r.status_code == 200 and data.get("plan"), "plans/current 可查")
        pending = next(
            (it for it in (data.get("plan") or {}).get("items", []) if it.get("status") == "pending"), None
        )
        if pending:
            r = await client.post(
                f"{BASE}/api/v1/checkins",
                json={"plan_item_id": pending["id"], "status": "partial", "feeling_score": 3},
                headers=H,
            )
            check(r.status_code == 200, "表单打卡 200")
        else:
            check(True, "表单打卡(当前无 pending 项,跳过)")

    # 9) 复原演示数据
    if not KEEP:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 复原演示数据 …")
        await regen()

    print(f"\nCHECK E2E: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
