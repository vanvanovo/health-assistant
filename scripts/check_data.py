# scripts/check_data.py
# P1 验收断言:表结构/扩展/数据量/时间范围。可重复执行。
# 用法:python scripts/check_data.py

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import asyncio  # noqa: E402

from sqlalchemy import text  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402
from backend.db.base import dispose_engine, get_engine  # noqa: E402

CHECKS: list[tuple[str, str, int]] = [
    # (说明, SQL, 最少条数)
    ("health_records 记录", "SELECT count(*) FROM health_records", 180),
    ("plans 计划", "SELECT count(*) FROM plans", 8),
    ("plan_items 打卡项", "SELECT count(*) FROM plan_items", 30),
    ("meals 饮食明细", "SELECT count(*) FROM meals", 100),
    ("nutrition_foods 营养库", "SELECT count(*) FROM nutrition_foods", 100),
    ("memory_events 事件记忆", "SELECT count(*) FROM memory_events", 1),
    ("users 演示账号", "SELECT count(*) FROM users WHERE username='health-demo'", 1),
    ("profile 画像", "SELECT count(*) FROM profile", 1),
]


async def main() -> int:
    configure_logging()
    s = get_settings()
    print(f"target: {s.pg_host}:{s.pg_port}/{s.pg_db}")
    engine = get_engine()
    failures = 0
    try:
        async with engine.connect() as conn:
            exts = (await conn.execute(text("SELECT extname FROM pg_extension"))).scalars().all()
            print(f"[ext] vector: {'OK' if 'vector' in exts else 'MISSING'}")

            tables = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='public'"
                    )
                )
            ).scalar_one()
            print(f"[tables] {tables} (>=14 {'OK' if tables >= 14 else 'FAIL'})")
            failures += 0 if tables >= 14 else 1

            for label, sql, min_rows in CHECKS:
                n = (await conn.execute(text(sql))).scalar_one()
                ok = n >= min_rows
                print(f"[{'OK' if ok else 'FAIL'}] {label}: {n} (>= {min_rows})")
                failures += 0 if ok else 1

            span = (
                await conn.execute(
                    text("SELECT min(date), max(date) FROM health_records")
                )
            ).one()
            print(f"[span] health_records: {span[0]} ~ {span[1]}")

            status_mix = (
                await conn.execute(
                    text(
                        "SELECT status, count(*) FROM plan_items GROUP BY status ORDER BY status"
                    )
                )
            ).all()
            print("[status] plan_items:", {k: v for k, v in status_mix})
    finally:
        await dispose_engine()

    if failures:
        print(f"CHECK DATA FAIL: {failures} 项未通过")
        return 1
    print("CHECK DATA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
