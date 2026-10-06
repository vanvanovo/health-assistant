# tests/test_llm.py
# P0 离线用例:provider 链降级逻辑(全 mock,不联网、不烧 token)。

from types import SimpleNamespace

import pytest

from backend.core.exceptions import LLMAPIError
from backend.core.llm import LLMClient, Provider, load_providers


def make_providers() -> list[Provider]:
    return [
        Provider("deepseek", "https://api.deepseek.com", "k1", "deepseek-v4-pro", True),
        Provider("deepseek-fallback", "https://api.deepseek.com", "k1", "deepseek-flash", True),
    ]


def patch_calls(monkeypatch, client: LLMClient, behaviors: dict):
    """替换 _call_provider:按 provider 名返回预设值或抛异常,并记录调用顺序。"""
    calls: list[str] = []

    def fake(provider, messages, temperature, max_tokens, timeout, disable_thinking):
        calls.append(provider.name)
        b = behaviors[provider.name]
        if isinstance(b, Exception):
            raise b
        return b

    monkeypatch.setattr(client, "_call_provider", fake)
    return calls


def test_primary_success(monkeypatch):
    client = LLMClient(make_providers())
    calls = patch_calls(monkeypatch, client, {"deepseek": "正常", "deepseek-fallback": "备用"})
    out = client.chat([{"role": "user", "content": "hi"}])
    assert out == "正常"
    assert calls == ["deepseek"]
    assert client.last_provider == "deepseek"
    assert client.last_model == "deepseek-v4-pro"


def test_primary_fail_switch_to_fallback(monkeypatch):
    client = LLMClient(make_providers())
    calls = patch_calls(
        monkeypatch,
        client,
        {"deepseek": RuntimeError("pro 超时"), "deepseek-fallback": "备用成功"},
    )
    out = client.chat([{"role": "user", "content": "hi"}])
    assert out == "备用成功"
    assert calls == ["deepseek", "deepseek-fallback"]  # 按序降级
    assert client.last_provider == "deepseek-fallback"


def test_empty_content_counts_as_failure(monkeypatch):
    """空正文视同失败:必须切到下一个 provider(health-planner 实测坑)。"""
    client = LLMClient(make_providers())
    calls = patch_calls(monkeypatch, client, {"deepseek": "   ", "deepseek-fallback": "备用正文"})
    out = client.chat([{"role": "user", "content": "hi"}])
    assert out == "备用正文"
    assert calls == ["deepseek", "deepseek-fallback"]


def test_all_fail_raises_llmapi_error(monkeypatch):
    client = LLMClient(make_providers())
    patch_calls(
        monkeypatch,
        client,
        {"deepseek": RuntimeError("挂了1"), "deepseek-fallback": RuntimeError("挂了2")},
    )
    with pytest.raises(LLMAPIError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    msg = str(ei.value)
    assert "deepseek" in msg and "deepseek-fallback" in msg


def test_only_param_restricts_chain(monkeypatch):
    client = LLMClient(make_providers())
    calls = patch_calls(monkeypatch, client, {"deepseek": "x", "deepseek-fallback": "y"})
    out = client.chat([{"role": "user", "content": "hi"}], only="deepseek-fallback")
    assert out == "y"
    assert calls == ["deepseek-fallback"]


def test_load_providers_from_settings():
    """链的构建:主 + 备必在;Kimi 空配置自动跳过。"""
    s = SimpleNamespace(
        base_url_deepseek="https://api.deepseek.com",
        api_key_deepseek="k",
        model_deepseek="deepseek-v4-pro",
        model_deepseek_fallback="deepseek-flash",
        base_url_kimi="",
        api_key_kimi="",
        model_kimi="",
        llm_disable_thinking=True,
    )
    names = [p.name for p in load_providers(s)]
    assert names == ["deepseek", "deepseek-fallback"]

    s.base_url_kimi = "https://kimi.example"
    s.api_key_kimi = "k2"
    s.model_kimi = "kimi-k2"
    names = [p.name for p in load_providers(s)]
    assert names == ["deepseek", "deepseek-fallback", "kimi"]
