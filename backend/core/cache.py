# backend/core/cache.py
# Redis 封装(P10):只服务三件事 —— 看板聚合缓存 / 意图路由缓存 / 写操作短锁。
# 纪律:Redis 不可用一律"透明降级"(缓存直查、锁放行),绝不阻塞主链路。

from __future__ import annotations

import asyncio
import json
import time
import uuid

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

_redis = None
_failed_until = 0.0


def _client():
    """惰性建连;失败后 30s 内不再重试(降级窗口)。Redis 不可用 → None。"""
    global _redis, _failed_until
    if _redis is not None:
        return _redis
    now = time.time()
    if now < _failed_until:
        return None
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        return _redis
    except Exception as e:  # noqa: BLE001
        logger.warning("cache.client_failed", error=str(e)[:120])
        _failed_until = now + 30
        return None


def _mark_failed(err: Exception) -> None:
    global _redis, _failed_until
    logger.warning("cache.op_failed", error=str(err)[:120])
    try:
        # 连接坏了就丢弃,等降级窗口结束后重建
        if _redis is not None:
            asyncio.get_running_loop().create_task(_redis.aclose())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    _redis = None
    _failed_until = time.time() + 30


async def cache_get(key: str):
    c = _client()
    if c is None:
        return None
    try:
        raw = await c.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        _mark_failed(e)
        return None


async def cache_set(key: str, value, ttl: int | None = None) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        ttl = ttl or get_settings().cache_ttl_dashboard
        await c.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
        return True
    except Exception as e:  # noqa: BLE001
        _mark_failed(e)
        return False


async def cache_delete(key: str) -> None:
    c = _client()
    if c is None:
        return
    try:
        await c.delete(key)
    except Exception:  # noqa: BLE001
        pass


class LockBusy(Exception):
    """写锁等待超时:另一笔请求正在处理同一目标。"""


async def acquire_lock(name: str, ttl: int | None = None, wait: float | None = None) -> str | None:
    """获取写锁。

    返回 token 表示持有;返回 None 表示 Redis 不可用(降级放行,不阻塞业务);
    等待超过 wait 仍被占用 → 抛 LockBusy。
    """
    c = _client()
    if c is None:
        return None
    s = get_settings()
    ttl = ttl or s.lock_ttl
    wait = s.lock_wait if wait is None else wait
    token = uuid.uuid4().hex
    deadline = time.time() + wait
    while True:
        try:
            ok = await c.set(name, token, nx=True, ex=ttl)
            if ok:
                return token
        except Exception as e:  # noqa: BLE001
            _mark_failed(e)
            return None
        if time.time() >= deadline:
            raise LockBusy(name)
        await asyncio.sleep(0.15)


async def release_lock(name: str, token: str | None) -> None:
    """释放:仅当锁值仍是自己的 token 才删(防误删他人锁)。"""
    if not token:
        return
    c = _client()
    if c is None:
        return
    try:
        cur = await c.get(name)
        if cur == token:
            await c.delete(name)
    except Exception:  # noqa: BLE001
        pass
