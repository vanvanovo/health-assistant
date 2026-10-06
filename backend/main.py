# backend/main.py
# 个人健康助手 · FastAPI 网关入口(含 MCP 子应用挂载与 X-MCP-Key 鉴权)。

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1 import api_router
from backend.config import get_settings
from backend.core import scheduler
from backend.core.assistant import init_assistant, saver_kind, shutdown_assistant
from backend.core.llm import load_providers
from backend.core.logger import configure_logging, get_logger
from backend.mcp.auth import ApiKeyAuthMiddleware
from backend.mcp.health_server import mcp as health_mcp

APP_VERSION = "0.1.0"

# MCP 子应用(mount 不会传播子应用 lifespan,需在 lifespan 中手动驱动)
_health_mcp_app = health_mcp.streamable_http_app()
_health_app = ApiKeyAuthMiddleware(_health_mcp_app, get_settings().mcp_shared_key)


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
        mcp_auth=bool(s.mcp_shared_key),
    )
    memory_kind = await init_assistant()
    log.info("app.memory_ready", kind=memory_kind)
    jobs_on = await scheduler.start_scheduler()
    log.info("app.jobs_ready", enabled=jobs_on)
    async with _health_mcp_app.router.lifespan_context(_health_mcp_app):
        log.info("app.started")
        yield
    await scheduler.stop_scheduler()
    await shutdown_assistant()
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

# 业务 API(认证 / 对话 SSE / 看板 / 计划 / 打卡)
app.include_router(api_router, prefix="/api/v1")

# MCP 健康工具(挂载前缀 /mcp/health,实际调用地址 {prefix}/mcp)
app.mount("/mcp/health", _health_app)


@app.get("/health")
async def health():
    """健康检查:P0 门禁用。"""
    s = get_settings()
    return {
        "status": "ok",
        "service": "health-assistant",
        "version": APP_VERSION,
        "llm_providers": [p.name for p in load_providers()],
        "memory": saver_kind(),
        "scheduler": scheduler.scheduler_running(),
    }


if __name__ == "__main__":
    import uvicorn

    _s = get_settings()
    uvicorn.run("backend.main:app", host=_s.app_host, port=_s.app_port)
