# backend/main.py
# 个人健康助手 · FastAPI 网关入口(P0 骨架版:健康检查 + 基础中间件)。

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.core.llm import load_providers
from backend.core.logger import configure_logging, get_logger

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("app")
    s = get_settings()
    # 只输出配置摘要,绝不输出密钥
    log.info(
        "app.start",
        port=s.app_port,
        llm_chain=[f"{p.name}:{p.model}" for p in load_providers()],
        pg=f"{s.pg_host}:{s.pg_port}/{s.pg_db}",
    )
    yield
    log.info("app.stop")


app = FastAPI(
    title="个人健康助手",
    description="基于 LangGraph 的个人健康管理助手(记录 → 分析 → 计划 → 打卡 → 反馈调整)",
    version=APP_VERSION,
    lifespan=lifespan,
)

# 前端 dev(Vite :3020)跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3020", "http://127.0.0.1:3020"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """健康检查:P0 门禁用。"""
    s = get_settings()
    return {
        "status": "ok",
        "service": "health-assistant",
        "version": APP_VERSION,
        "llm_providers": [p.name for p in load_providers()],
    }


if __name__ == "__main__":
    import uvicorn

    _s = get_settings()
    uvicorn.run("backend.main:app", host=_s.app_host, port=_s.app_port)
