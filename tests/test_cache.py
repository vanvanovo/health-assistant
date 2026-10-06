# tests/test_cache.py
# Redis 封装离线用例:命中/未命中/降级/写锁(忙等待与释放语义)。

import pytest

from backend.core import cache


class FakeRedis:
    def __init__(self):
        self.store: dict = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def delete(self, k):
        self.store.pop(k, None)


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cache, "_client", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_cache_roundtrip(fake_redis):
    assert await cache.cache_set("k1", {"a": 1}, ttl=5)
    assert await cache.cache_get("k1") == {"a": 1}
    assert await cache.cache_get("missing") is None


@pytest.mark.asyncio
async def test_cache_degrade_when_no_redis(monkeypatch):
    monkeypatch.setattr(cache, "_client", lambda: None)
    assert await cache.cache_get("k") is None
    assert await cache.cache_set("k", 1) is False
    assert await cache.acquire_lock("lock:any") is None    # 降级放行


@pytest.mark.asyncio
async def test_lock_acquire_and_release(fake_redis):
    token = await cache.acquire_lock("lock:x", ttl=5, wait=0.1)
    assert token
    await cache.release_lock("lock:x", token)
    assert await fake_redis.get("lock:x") is None


@pytest.mark.asyncio
async def test_lock_busy_raises(fake_redis):
    await cache.acquire_lock("lock:y", ttl=5, wait=0.1)
    with pytest.raises(cache.LockBusy):
        await cache.acquire_lock("lock:y", ttl=5, wait=0.1)


@pytest.mark.asyncio
async def test_release_with_foreign_token_is_noop(fake_redis):
    token = await cache.acquire_lock("lock:z", ttl=5, wait=0.1)
    await cache.release_lock("lock:z", "someone-elses-token")
    assert await fake_redis.get("lock:z") == token
