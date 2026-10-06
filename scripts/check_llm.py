# scripts/check_llm.py
# P0 冒烟:真实调用 主/备 模型 + 演示降级链(假主模型失败 → 自动切真备用)。
# 用法:python scripts/check_llm.py

import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from backend.core.exceptions import LLMAPIError  # noqa: E402
from backend.core.llm import LLMClient, Provider, load_providers  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402

MSGS = [{"role": "user", "content": "只回复两个字:正常"}]


def main() -> int:
    configure_logging()
    providers = load_providers()
    print("chain:", [f"{p.name}:{p.model}" for p in providers])
    if not providers:
        print("FAIL: .env 未配置任何 provider")
        return 1

    client = LLMClient(providers)

    # ① 主模型真实调用
    t0 = time.time()
    try:
        out = client.chat(MSGS, only="deepseek")
        print(f"[1/3] primary ok: model={client.last_model} elapsed={time.time()-t0:.1f}s reply={out[:20]!r}")
    except LLMAPIError as e:
        print(f"[1/3] primary FAIL: {e}")
        return 1

    # ② 备用模型真实调用(如配置了)
    if any(p.name == "deepseek-fallback" for p in providers):
        t0 = time.time()
        out = client.chat(MSGS, only="deepseek-fallback")
        print(f"[2/3] fallback ok: model={client.last_model} elapsed={time.time()-t0:.1f}s reply={out[:20]!r}")
    else:
        print("[2/3] fallback 未配置,跳过")

    # ③ 降级链演示:坏 Key 的假主模型(401)→ 自动切真备用
    broken = Provider("broken-primary", providers[0].base_url, "sk-invalid-key-for-demo", providers[0].model)
    chain_client = LLMClient([broken] + providers)
    t0 = time.time()
    try:
        out = chain_client.chat(MSGS)
        print(
            f"[3/3] fallback chain ok: used={chain_client.last_provider} elapsed={time.time()-t0:.1f}s reply={out[:20]!r}"
        )
    except LLMAPIError as e:
        print(f"[3/3] fallback chain FAIL: {e}")
        return 1

    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
