# scripts/check_cloud.py
# 云端轻量部署公网冒烟:经 Nginx :8080 → 网关,验证 401/登录/规则/知识降级/高危拦截/记录/看板。
# 用法(本机):$env:HEALTH_BASE_URL="http://<公网IP>:8080"; python scripts/check_cloud.py
# 说明:云端 RAG 未部署,知识问答预期走降级话术(明确标注"知识库暂不可用")。

import asyncio
import json
import os
import sys

import httpx

BASE = os.environ.get("HEALTH_BASE_URL", "http://127.0.0.1:8080")
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


def intents_of(events):
    return [e["data"].get("intents") for e in has(events, "routing")]


async def main() -> int:
    print(f"== 云端冒烟:{BASE} ==")
    timeout = httpx.Timeout(240.0, connect=15.0)
    limits = httpx.Limits(max_keepalive_connections=0, max_connections=10)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, limits=limits) as client:
        # 1) 鉴权:未登录 401
        r = await client.post(f"{BASE}/api/v1/chat/stream", json={"message": "hi"})
        check(r.status_code == 401, "未带 token → 401")

        # 2) 登录
        r = await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        token = r.json().get("access_token") if r.status_code == 200 else None
        check(bool(token), "公网登录成功")
        H = {"Authorization": f"Bearer {token}"}

        # 3) 规则前置(零 token)
        evs = await sse(client, token, "你好")
        check(intents_of(evs) == [["rule"]], "规则前置(routing=rule)")
        check("个人健康助手" in text_of(evs), "帮助文案直答")

        # 4) 知识问答 → RAG 未部署 → 降级话术
        evs = await sse(client, token, "晚上总是睡不好,有什么改善建议")
        check(any("knowledge" in (x or []) for x in intents_of(evs)), "知识路由(routing=knowledge)")
        check("知识库暂不可用" in text_of(evs), "知识降级话术(标注知识库暂不可用)")
        check(any(m["data"].get("degraded") for m in has(evs, "meta")), "meta.degraded=True")

        # 5) 高危拦截(零 token 规则,最高优先)
        evs = await sse(client, token, "我胸痛应该吃什么药")
        check(intents_of(evs) == [["safety"]], "高危拦截(routing=safety)")
        check("120" in text_of(evs) or "就医" in text_of(evs), "就医引导")
        check(has(evs, "meta")[0]["data"].get("safety", {}).get("level") == "high", "meta.safety=high")

        # 6) 记录写入(带回执卡)
        evs = await sse(client, token, "今天跑了5公里,体重68.2")
        check(any("record" in (x or []) for x in intents_of(evs)), "记录路由(routing=record)")
        check(any(c["data"].get("type") == "record_confirm" for c in has(evs, "card")), "记录确认卡")

        # 7) 看板 & 画像走公网(数据面可用)
        r = await client.get(f"{BASE}/api/v1/dashboard/overview", headers=H)
        check(r.status_code == 200, "看板 overview 200")
        r = await client.get(f"{BASE}/api/v1/profile", headers=H)
        check(r.status_code == 200, "画像接口 200")

    print(f"== 结果:{_ok} 通过 / {_fail} 失败 ==")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
