# backend/core/retry.py
# 三层兜底:自动重试(3 次 1s/2s/4s)→ 业务降级 → 系统兜底。
# 用法(Agent/工具调用外层):
#   @with_retry(agent_type="planner")
#   async def _invoke(): ...

import asyncio
from functools import wraps
from typing import Any, Callable, Optional

from backend.core.exceptions import AuthenticationError, InvalidInputError
from backend.core.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 3                  # 重试 3 次(加首次共 4 次尝试)
RETRY_DELAYS = [1.0, 2.0, 4.0]   # 指数退避(面试口径)
TIMEOUT_PER_ATTEMPT = 30.0       # 单次尝试超时

# 不可重试:重试也没用,立即抛
NON_RETRYABLE_ERRORS = (InvalidInputError, AuthenticationError)


class FallbackHandler:
    """第二层:按 agent_type 的专项降级(尽量保住核心功能,退化为更简单的实现)。"""

    FALLBACK_TEXTS: dict[str, str] = {
        "recorder": "记录服务暂时不可用,请稍后再试一次,我已保留你刚才的输入。",
        "analyst": "统计服务暂时不可用,请稍后重试。",
        "planner": "计划生成暂时不可用,你既有的计划不受影响,请稍后重试。",
        "nutrition": "饮食服务暂时不可用,请稍后重试。",
        "knowledge": "知识库暂时不可用,以下为通用建议,仅供参考、不构成医疗建议。",
    }
    SYSTEM_FALLBACK = "服务暂时不可用,请稍后再试。"

    @classmethod
    async def handle(cls, agent_type: str, original_error: Optional[Exception]) -> dict:
        text = cls.FALLBACK_TEXTS.get(agent_type, cls.SYSTEM_FALLBACK)
        logger.info("retry.agent_fallback", agent_type=agent_type)
        return {"content": text, "fallback_used": True, "degraded": True, "structured_output": None}


def _system_fallback(agent_type: str, last_error: Optional[Exception]) -> dict:
    logger.error("retry.system_fallback", agent_type=agent_type, error=str(last_error))
    return {
        "content": "非常抱歉,服务暂时不可用,请稍后再试。",
        "fallback_used": True,
        "degraded": True,
        "system_fallback": True,
        "structured_output": None,
    }


def with_retry(agent_type: str = ""):
    """三层兜底装饰器工厂(异步函数)。返回 dict(含 content / degraded 标记)。"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # ── 第一层:自动重试 ──
            last_error: Optional[Exception] = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=TIMEOUT_PER_ATTEMPT)
                    if attempt > 0:
                        logger.info("retry.succeeded", agent_type=agent_type, attempt=attempt + 1)
                    return result
                except NON_RETRYABLE_ERRORS:
                    raise
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    if attempt < MAX_RETRIES:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "retry.attempt_failed",
                            agent_type=agent_type,
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)

            # ── 第二层:业务降级 ──
            try:
                return await FallbackHandler.handle(agent_type=agent_type, original_error=last_error)
            except Exception as fe:  # noqa: BLE001
                logger.error("retry.fallback_failed", agent_type=agent_type, error=str(fe))

            # ── 第三层:系统兜底(永不失败)──
            return _system_fallback(agent_type, last_error)

        return wrapper

    return decorator
