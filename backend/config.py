# backend/config.py
# 全项目唯一的「配置中心」:从 .env 读取所有配置项,供任何模块取用。
# 密钥类字段一律只在 .env,代码里不留真值、日志里不输出。

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录(backend/ 的上一级),保证不管从哪运行都能找到 .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    # ── 应用基础 ──────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8020
    log_level: str = "INFO"
    app_version: str = "0.1.0"

    # ── LLM provider 链(主 → 备;第三方 provider 填齐即入链)──
    base_url_deepseek: str = ""
    api_key_deepseek: str = ""
    model_deepseek: str = ""
    model_deepseek_fallback: str = ""
    base_url_kimi: str = ""
    api_key_kimi: str = ""
    model_kimi: str = ""
    llm_disable_thinking: bool = True   # 官方接口实测支持 thinking disabled,低延迟场景默认关
    llm_timeout_seconds: float = 90.0
    llm_max_tokens: int = 1024
    llm_retry_times: int = 3

    # ── PostgreSQL + pgvector(P1)──────────────────────────────
    pg_host: str = "localhost"
    pg_port: int = 5434
    pg_user: str = "health"
    pg_password: str = ""
    pg_db: str = "health_assistant"

    @property
    def database_url(self) -> str:
        """SQLAlchemy(asyncpg)连接串;密码只在运行时使用,不落日志。"""
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    # ── Redis(V4 启用,先留位)────────────────────────────────
    redis_url: str = "redis://localhost:6381/0"

    # ── 安全与账号 ────────────────────────────────────────────
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 10080
    mcp_shared_key: str = ""
    demo_username: str = "health-demo"
    demo_password: str = "health-demo"

    # ── 超时(对齐面试口径)────────────────────────────────────
    mcp_timeout_seconds: int = 5
    mcp_health_url: str = "http://localhost:8020/mcp/health"   # MCP 健康工具挂载前缀(调用地址 = {url}/mcp)

    # ── 嵌入(P9 启用,先留位)─────────────────────────────────
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-m3"

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False,   # DB_HOST 能对应 db_host
        extra="ignore",         # .env 里多余的字段不报错
        protected_namespaces=(),  # 允许 model_deepseek 这类以 model_ 开头的字段名
    )


@lru_cache()
def get_settings() -> Settings:
    """获取全局唯一配置对象(只创建一次、只读一次文件)。"""
    return Settings()
