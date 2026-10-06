# scripts/demo_reset.py
# 一键复原演示环境:重灌演示数据 + 清会话记忆(checkpoint)+ 清演示缓存(Redis 可用时)。
# 用途:录屏/演示/面试前把环境恢复到初始状态。用法:python scripts/demo_reset.py

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import asyncio  # noqa: E402

from sqlalchemy import text  # noqa: E402

from backend.core.logger import configure_logging  # noqa: E402
from backend.db.base import dispose_engine, get_engine  # noqa: E402


async def _clear_checkpoints() -> None:
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            for tbl in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                try:
                    await conn.execute(text(f"TRUNCATE {tbl}"))
                    print(f"  [ok] 清空 {tbl}")
                except Exception as e:  # noqa: BLE001
                    print(f"  [skip] {tbl}: {str(e)[:80]}")
    finally:
        await dispose_engine()


async def _clear_demo_cache() -> None:
    from backend.core import cache

    c = cache._client()
    if c is None:
        print("  [skip] Redis 不可用,跳过缓存清理")
        return
    removed = 0
    try:
        async for key in c.scan_iter("cache:*"):
            await c.delete(key)
            removed += 1
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 缓存清理异常:{str(e)[:100]}")
    print(f"  [ok] 清理演示缓存 {removed} 个键")


async def main() -> int:
    configure_logging()
    print("[1/3] 清空会话记忆(checkpoint)…")
    await _clear_checkpoints()

    print("[2/3] 重灌演示数据…")
    from gen_demo_data import main as regen  # noqa: E402

    code = await regen()
    if code != 0:
        print("DEMO RESET FAIL")
        return 1

    print("[3/3] 清理演示缓存…")
    await _clear_demo_cache()

    print("DEMO RESET DONE(刷新页面即为初始演示状态;账号 health-demo / health-demo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
