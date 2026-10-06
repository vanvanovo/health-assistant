# scripts/init_db.py
# P1:幂等建库建表(pgvector 扩展 + 全部表)。可重复执行,不删数据。
# 用法:python scripts/init_db.py

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import asyncio  # noqa: E402

from sqlalchemy import text  # noqa: E402

import backend.db.models  # noqa: F401  确保所有表注册进 metadata  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.core.logger import configure_logging, get_logger  # noqa: E402
from backend.db.base import Base, dispose_engine, get_engine  # noqa: E402


async def main() -> int:
    configure_logging()
    log = get_logger("init_db")
    s = get_settings()
    print(f"target: {s.pg_host}:{s.pg_port}/{s.pg_db}")

    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)

        async with engine.connect() as conn:
            tables = (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' ORDER BY table_name"
                    )
                )
            ).scalars().all()
            exts = (await conn.execute(text("SELECT extname FROM pg_extension"))).scalars().all()

        print(f"tables({len(tables)}): " + ", ".join(tables))
        print("extensions: " + ", ".join(exts))
        if "vector" not in exts:
            print("FAIL: vector 扩展未启用")
            return 1
        if len(tables) < 14:
            print(f"FAIL: 表数量不足({len(tables)} < 14)")
            return 1
        log.info("init_db.ok", tables=len(tables))
        print("INIT DB PASS")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
