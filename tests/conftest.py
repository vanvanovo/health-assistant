# tests/conftest.py
# 测试隔离:默认让 Redis 层处于"不可用降级"状态 —— 测试不吃真实缓存/锁,保证确定性。
# 需要测缓存本身的用例在用例内显式 monkeypatch cache._client 为 FakeRedis。

import pytest

from backend.core import cache


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    monkeypatch.setattr(cache, "_client", lambda: None)
    cache._failed_until = 0.0
    yield
    cache._failed_until = 0.0
