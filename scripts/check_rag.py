# scripts/check_rag.py
# P9 验收:知识问答(A2A RAG,带来源)+ 安全边界 + 关停降级。
# 用法(分两步,便于验证"关停只降级"):
#   python scripts/check_rag.py phase1   # RAG Agent 运行中:A2A 直连 + 网关问答 + 高危拦截
#   (停掉 services/rag_agent/server.py)
#   python scripts/check_rag.py phase2   # RAG 关停:主链路只降级不 500;结束复原数据
#   python scripts/check_rag.py restore

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

import httpx  # noqa: E402

from backend.core.a2a_client import call_health_rag  # noqa: E402
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


async def phase1() -> int:
    # ① A2A 直连(不经过网关)
    data = await call_health_rag("晚上睡不好怎么办")
    check(data.get("answer_mode") == "rag", f"A2A 直连 answer_mode=rag(实际 {data.get('answer_mode')})")
    check(len(data.get("sources") or []) >= 1, f"带来源 {len(data.get('sources') or [])} 条")
    check("仅供参考" in (data.get("answer") or ""), "回答含免责声明")

    limits = httpx.Limits(max_keepalive_connections=0, max_connections=20)
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0), trust_env=False, limits=limits) as client:
        token = (await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})).json()["access_token"]

        # ② 网关链路:知识问答
        evs = await sse(client, token, "晚上睡不好怎么办?")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["knowledge"]], "网关 routing=knowledge")
        src = [c for c in has(evs, "card") if c["data"]["type"] == "sources"]
        check(bool(src), "网关回答带来源卡")
        check("仅供参考" in text_of(evs), "网关回答含免责声明")

        # ③ 安全边界:高危拦截(网关侧,最高优先)
        evs = await sse(client, token, "我胸痛应该吃什么药")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["safety"]], "高危 routing=safety")
        text = text_of(evs)
        check("120" in text and "就医" in text, "就医/急救引导")
        check(has(evs, "meta")[0]["data"].get("safety", {}).get("level") == "high", "meta.safety=high")
        check(not [c for c in has(evs, "card") if c["data"]["type"] == "sources"], "高危不返回来源/建议")

    print(f"\nCHECK RAG PHASE1: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


async def phase2() -> int:
    limits = httpx.Limits(max_keepalive_connections=0, max_connections=20)
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0), trust_env=False, limits=limits) as client:
        token = (await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})).json()["access_token"]
        evs = await sse(client, token, "晚上睡不好怎么办?")
        check([e["data"]["intents"] for e in has(evs, "routing")] == [["knowledge"]], "关停后 routing 仍=knowledge")
        text = text_of(evs)
        check("知识库暂不可用" in text, "降级话术明确标注")
        check(has(evs, "meta")[0]["data"].get("degraded") is True, "meta.degraded=true")
        check(evs and evs[-1]["event"] == "done", "不 500,正常结束")

    if "norestore" not in sys.argv:
        from gen_demo_data import main as regen  # noqa: E402
        print("\n[restore] 复原演示数据 …")
        await regen()
    print(f"\nCHECK RAG PHASE2: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
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
    print("用法:python scripts/check_rag.py phase1|phase2|restore")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
