# scripts/check_memory.py
# P6 验收:多轮指代(重启前后)+ 记忆确认写入闭环 + 画像/事件 REST。
# 用法(网关需已启动):
#   python scripts/check_memory.py phase1    # 第一轮对话 + 记忆确认卡 + apply 落库
#   (重启网关)
#   python scripts/check_memory.py phase2    # 重启后「那这周呢?」仍懂指代;结束复原数据
#   python scripts/check_memory.py restore   # 仅复原演示数据

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402

from backend.core.logger import configure_logging  # noqa: E402

BASE = os.environ.get("HEALTH_BASE_URL", "http://127.0.0.1:8020")
USERNAME, PASSWORD = "health-demo", "health-demo"

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
        json={"message": message}, headers={"Authorization": f"Bearer {token}"},
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


async def _login(client) -> str:
    r = await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return r.json()["access_token"]


async def phase1() -> int:
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0), trust_env=False) as client:
        # 0) 记忆层类型(应为 postgres)
        h = await client.get(f"{BASE}/health")
        check(h.json().get("memory") == "postgres", f"记忆层 = postgres(实际 {h.json().get('memory')})")

        token = await _login(client)
        H = {"Authorization": f"Bearer {token}"}

        # 1) 第一轮对话(写入会话记忆)
        evs = await sse(client, token, "我最近一个月状态怎么样?")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["analyze"]], "第一轮:analyze 正常返回")

        # 2) 画像记忆:确认卡 → apply → 落库
        evs = await sse(client, token, "我膝盖不好,以后别给我排深蹲跳")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["memory"]], "画像语句 routing=memory")
        cards = [c for c in has(evs, "card") if c["data"]["type"] == "profile_update"]
        check(bool(cards) and cards[0]["data"]["payload"]["status"] == "pending", "返回待确认画像卡")
        card_token = cards[0]["data"]["payload"]["token"] if cards else ""
        r = await client.post(f"{BASE}/api/v1/memory/apply", json={"token": card_token}, headers=H)
        check(r.status_code == 200 and r.json().get("status") == "applied", "确认写入 → applied")
        prof = (await client.get(f"{BASE}/api/v1/profile", headers=H)).json()
        check(any("膝" in str(x) for x in (prof.get("injuries") or [])), "画像 injuries 已含膝盖条目")

        # 3) 事件记忆:确认卡 → apply → 事件可查
        evs = await sse(client, token, "下周一到周三出差")
        cards = [c for c in has(evs, "card") if c["data"]["type"] == "profile_update"]
        check(bool(cards) and cards[0]["data"]["payload"].get("event"), "返回待确认事件卡")
        ev_token = cards[0]["data"]["payload"]["token"] if cards else ""
        r = await client.post(f"{BASE}/api/v1/memory/apply", json={"token": ev_token}, headers=H)
        check(r.status_code == 200 and r.json().get("kind") == "event", "事件确认写入 → applied")
        ev_applied = r.json().get("event") or {}
        q_date = ev_applied.get("start_date") or ""
        evs2 = await client.get(f"{BASE}/api/v1/memory/events", params={"date": q_date}, headers=H)
        check(any("出差" in str(e.get("description")) for e in evs2.json().get("events", [])),
              f"事件列表可查(生效日 {q_date})")
        evs_today = await client.get(f"{BASE}/api/v1/memory/events", headers=H)
        check(not any(str(e.get("id")) == str(ev_applied.get("event_id"))
                      for e in evs_today.json().get("events", [])),
              "未生效(未来)事件不出现在今天列表")

        # 4) 篡改 token 应被拒绝
        r = await client.post(f"{BASE}/api/v1/memory/apply", json={"token": card_token[:-4] + "abcd"}, headers=H)
        check(r.status_code == 400, "篡改 token → 400")

    print(f"\nCHECK MEMORY PHASE1: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


async def phase2() -> int:
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0), trust_env=False) as client:
        token = await _login(client)
        evs = await sse(client, token, "那这周呢?")
        routed = [e["data"] for e in has(evs, "routing")]
        intents = routed[0]["intents"] if routed else []
        slots = routed[0].get("slots") if routed else {}
        check(intents == ["analyze"], f"重启后指代识别:intents={intents}")
        check(int(slots.get("days") or 0) == 7, f"指代正确收敛到近 7 天(days={slots.get('days')})")

    if "norestore" not in sys.argv:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 复原演示数据 …")
        await regen()
    print(f"\nCHECK MEMORY PHASE2: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


async def restore() -> int:
    from gen_demo_data import main as regen  # noqa: E402
    await regen()
    return 0


async def main() -> int:
    configure_logging()
    phase = sys.argv[1] if len(sys.argv) > 1 else "phase1"
    if phase == "phase1":
        return await phase1()
    if phase == "phase2":
        return await phase2()
    if phase == "restore":
        return await restore()
    print("用法:python scripts/check_memory.py phase1|phase2|restore")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
