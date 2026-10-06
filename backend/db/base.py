# backend/db/base.py
# 数据库基础:声明基类 + 异步引擎/会话工厂 + FastAPI 会话依赖。
# 引擎懒加载:import 本模块不会尝试连库(脚本/测试更友好)。

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings


class Base(DeclarativeBase):
    """所有表模型的基类;DDL 单一事实来源(scripts/init_db.py 用 metadata 建表)。"""


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    """全局唯一异步引擎(懒加载)。"""
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            # 实测坑(2026-10-06):asyncpg + pool_pre_ping 在 checkout 时 ping 会触发
            # MissingGreenlet(greenlet_spawn has not been called)——改为 pool_recycle 防陈旧连接。
            pool_pre_ping=False,
            pool_recycle=1800,          # 30 分钟回收,防休眠/空闲后的死连接
            pool_size=5,
            max_overflow=5,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖:async with 会话,请求结束自动关闭。"""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """进程退出时释放连接池(脚本/测试用)。"""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
