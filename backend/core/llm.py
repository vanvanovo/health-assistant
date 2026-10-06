# backend/core/llm.py
# 统一 LLM 客户端:provider 链按序降级(deepseek-v4-pro 主 → deepseek-flash 备 → 第三方预留)。
# 规矩:所有 Agent 必须通过此模块调用模型,禁止直连 SDK。
# 机制(继承 health-planner 并实测):
#   1) 按 provider 顺序尝试,单个失败自动切下一个
#   2) 空正文视同失败(思考模型可能把 max_tokens 全花在思考上)
#   3) 全部失败才抛 LLMAPIError,由上层三层容错接管

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.config import get_settings
from backend.core.exceptions import LLMAPIError
from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Provider:
    """一个模型通道:显示名 + 接口地址 + Key + 模型名 + 是否关闭思考。"""

    name: str
    base_url: str
    api_key: str
    model: str
    disable_thinking: bool = True


def load_providers(settings=None) -> list[Provider]:
    """从配置构造 provider 链。顺序 = 降级顺序;配置不完整的直接跳过(不炸)。"""
    s = settings or get_settings()
    providers: list[Provider] = []

    # 主:deepseek-v4-pro
    if s.base_url_deepseek and s.api_key_deepseek and s.model_deepseek:
        providers.append(
            Provider("deepseek", s.base_url_deepseek, s.api_key_deepseek, s.model_deepseek, s.llm_disable_thinking)
        )
    # 备:同门快速模型(模型级降级)
    if s.base_url_deepseek and s.api_key_deepseek and s.model_deepseek_fallback:
        providers.append(
            Provider(
                "deepseek-fallback",
                s.base_url_deepseek,
                s.api_key_deepseek,
                s.model_deepseek_fallback,
                s.llm_disable_thinking,
            )
        )
    # 第三方 provider 预留(Kimi 等):填齐三项自动入链,零代码改动
    if s.base_url_kimi and s.api_key_kimi and s.model_kimi:
        providers.append(
            Provider("kimi", s.base_url_kimi, s.api_key_kimi, s.model_kimi, s.llm_disable_thinking)
        )

    if not providers:
        logger.warning("llm.no_provider_configured")
    return providers


def _to_lc_messages(messages: list[dict]):
    """dict 消息 → LangChain 消息对象。"""
    out = []
    for m in messages:
        role = (m.get("role") or "user").lower()
        content = m.get("content") or ""
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _extract_text(resp) -> str:
    """兼容取文本:优先 .text,其次 content。"""
    text = getattr(resp, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(resp, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


class LLMClient:
    """provider 链客户端:按序尝试、空正文视同失败、全挂抛 LLMAPIError。"""

    def __init__(self, providers: list[Provider] | None = None):
        self._providers = providers if providers is not None else load_providers()
        self.last_provider: str | None = None  # 最近一次成功响应的 provider 名,上层可读
        self.last_model: str | None = None

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers)

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        disable_thinking: bool | None = None,
        only: str | None = None,
    ) -> str:
        """按 provider 链调用,返回正文文本。

        only=provider 名 时只试该通道(冒烟/定向测试用)。
        temperature=None 时不发送该参数(思考模型对温度敏感,交给模型默认)。
        """
        s = get_settings()
        max_tokens = max_tokens or s.llm_max_tokens
        timeout = timeout or s.llm_timeout_seconds

        candidates = [p for p in self._providers if only is None or p.name == only]
        if not candidates:
            raise LLMAPIError(f"没有可用模型配置(only={only}, chain={[p.name for p in self._providers]})")

        errors: list[str] = []
        for p in candidates:
            t0 = time.time()
            try:
                content = self._call_provider(p, messages, temperature, max_tokens, timeout, disable_thinking)
                if not content.strip():
                    raise LLMAPIError("返回空正文(可能 max_tokens 全被思考 token 消耗)")
                self.last_provider, self.last_model = p.name, p.model
                logger.info(
                    "llm.ok",
                    provider=p.name,
                    model=p.model,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
                return content
            except Exception as e:  # noqa: BLE001 —— 任意可预期失败都走降级,最后统一抛
                errors.append(f"{p.name}({p.model}): {type(e).__name__}: {e}")
                logger.warning(
                    "llm.fail", provider=p.name, model=p.model, error=str(e), elapsed_ms=int((time.time() - t0) * 1000)
                )
        raise LLMAPIError("所有模型不可用 | " + " || ".join(errors))

    def _call_provider(
        self,
        provider: Provider,
        messages: list[dict],
        temperature: float | None,
        max_tokens: int,
        timeout: float,
        disable_thinking: bool | None,
    ) -> str:
        """单通道调用(测试里 monkeypatch 这一层,无需打真实 API)。"""
        disable = provider.disable_thinking if disable_thinking is None else disable_thinking
        # trust_env=False:绕过系统代理(Windows 系统代理会让 TLS 握手失败;国内直连即可)
        http_client = httpx.Client(trust_env=False, timeout=httpx.Timeout(timeout, connect=15.0))
        kwargs: dict = dict(
            model=provider.model,
            api_key=provider.api_key,
            base_url=provider.base_url,
            max_tokens=max_tokens,
            max_retries=0,
            http_client=http_client,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if disable:
            # 官方接口实测支持;低延迟场景关闭思考,避免 max_tokens 被思考吃光
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        llm = ChatOpenAI(**kwargs)
        resp = llm.invoke(_to_lc_messages(messages))
        return _extract_text(resp)


_shared_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """模块级共享客户端(provider 配置改动后请重建进程/实例)。"""
    global _shared_client
    if _shared_client is None:
        _shared_client = LLMClient()
    return _shared_client


def reset_llm_client() -> None:
    """清空共享实例(测试/配置热更新用)。"""
    global _shared_client
    _shared_client = None
