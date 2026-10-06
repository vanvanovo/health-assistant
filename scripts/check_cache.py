# scripts/check_cache.py
# P10 验收:写锁(忙等待/释放)/ 看板缓存(命中提速)/ 路由缓存 / Redis 关停透明降级。
# 用法(先 docker compose --profile v4 up -d redis):
#   python scripts/check_cache.py phase1
#   (docker compose --profile v4 stop redis)
#   python scripts/check_cache.py phase2

import os
import sys
import time
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

import httpx  # noqa: E402

from backend.core import cache  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402
from backend.core.router import route_intent  # noqa: E402

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


def _limits():
    return httpx.Limits(max_keepalive_connections=0, max_connections=20)


async def _login(client) -> str:
    r = await client.post(f"{BASE}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return r.json()["access_token"]


async def phase1() -> int:
    # ① 写锁语义:占用 → 忙 → 释放 → 可再取
    token = await cache.acquire_lock("lock:check:p10", ttl=5, wait=0.2)
    check(bool((token)), "获取写锁成功")
    try:
        try:
            await cache.acquire_lock("lock:check:p10", ttl=5, wait=0.2)
            check(False, "锁被占用时第二次获取应抛 LockBusy")
        except cache.LockBusy:
            check(True, "锁被占用时第二次获取 → LockBusy(忙提示)")
    finally:
        await cache.release_lock("lock:check:p10", token)
    token2 = await cache.acquire_lock("lock:check:p10", ttl=5, wait=0.2)
    check(bool(token2), "释放后可重新获取")
    await cache.release_lock("lock:check:p10", token2)

    # ② 看板缓存:第二次请求显著更快 + 缓存键已写入
    key = f"cache:dash:overview:{date.today().isoformat()}"
    await cache.cache_delete(key)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False, limits=_limits()) as client:
        token_h = {"Authorization": f"Bearer {await _login(client)}"}
        t0 = time.perf_counter()
        r1 = await client.get(f"{BASE}/api/v1/dashboard/overview", headers=token_h)
        t1 = time.perf_counter() - t0
        t0 = time.perf_counter()
        r2 = await client.get(f"{BASE}/api/v1/dashboard/overview", headers=token_h)
        t2 = time.perf_counter() - t0
        check(r1.status_code == 200 and r2.status_code == 200, "overview 两次都 200")
        check(t2 < t1, f"第二次更快({t2 * 1000:.0f}ms < {t1 * 1000:.0f}ms)")
        check(await cache.cache_get(key) is not None, "看板缓存键已写入")

    # ③ 路由缓存:同句两次,第二次走缓存(无上下文时启用)
    msg = "今天慢跑5公里,体重68.2"
    t0 = time.perf_counter()
    r1 = await route_intent(msg)
    t1 = time.perf_counter() - t0
    t0 = time.perf_counter()
    r2 = await route_intent(msg)
    t2 = time.perf_counter() - t0
    check(r2 == r1 and t2 < t1, f"路由缓存生效({t2 * 1000:.0f}ms < {t1 * 1000:.0f}ms)")

    print(f"\nCHECK CACHE PHASE1: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


async def phase2() -> int:
    # Redis 已停:一切透明降级,主链路不受影响
    check(await cache.cache_get("any:key") is None, "缓存读取降级 → None")
    check(await cache.acquire_lock("lock:check:p10b") is None, "写锁降级 → 放行(None)")

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False, limits=_limits()) as client:
        token_h = {"Authorization": f"Bearer {await _login(client)}"}
        r = await client.get(f"{BASE}/api/v1/dashboard/overview", headers=token_h)
        check(r.status_code == 200, "Redis 关停 overview 仍 200(直查降级)")
        key = f"cache:dash:overview:{date.today().isoformat()}"
        check(await cache.cache_get(key) is None, "降级期间不写缓存(直查)")

    print(f"\nCHECK CACHE PHASE2: {'PASS' if _fail == 0 else 'FAIL'} (ok={_ok}, fail={_fail})")
    return 0 if _fail == 0 else 1


async def main() -> int:
    configure_logging()
    phase = sys.argv[1] if len(sys.argv) > 1 else "phase1"
    if phase == "phase1":
        return await phase1()
    if phase == "phase2":
        return await phase2()
    print("用法:python scripts/check_cache.py phase1|phase2")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
