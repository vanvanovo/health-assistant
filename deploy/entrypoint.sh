#!/bin/sh
# gateway 容器入口:幂等建表 → 可选灌演示数据 → 启动网关
# SEED_DEMO=true(默认)= 每次启动重灌演示数据(演示友好);设 false 保留数据
set -e

echo "[entrypoint] init db ..."
python scripts/init_db.py

if [ "${SEED_DEMO:-true}" = "true" ]; then
  echo "[entrypoint] seed demo data ..."
  python scripts/gen_demo_data.py
fi

echo "[entrypoint] starting gateway ..."
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8020
