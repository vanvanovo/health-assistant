# backend/core/logger.py
# 全项目日志工具:在标准库 logging 之上包装「事件名 + 键值对」的结构化写法。
# 控制台 + logs/app.log 双输出(TimedRotating 手动滚动由部署承担)。

import logging
import logging.handlers
import os
import sys

from backend.config import get_settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

_configured = False


class _Logger:
    """结构化日志包装:logger.info("event.name", key=value) 或 logger.info("模板 %s", 值)。"""

    def __init__(self, name: str):
        self._log = logging.getLogger(name)

    def _fmt(self, event: str, **kw) -> str:
        if kw:
            return event + " | " + " ".join(f"{k}={v!r}" for k, v in kw.items())
        return event

    def debug(self, event: str, *args, **kw):
        if args:
            self._log.debug(event, *args)
        else:
            self._log.debug(self._fmt(event, **kw))

    def info(self, event: str, *args, **kw):
        if args:
            self._log.info(event, *args)
        else:
            self._log.info(self._fmt(event, **kw))

    def warning(self, event: str, *args, **kw):
        if args:
            self._log.warning(event, *args)
        else:
            self._log.warning(self._fmt(event, **kw))

    def error(self, event: str, *args, **kw):
        if args:
            self._log.error(event, *args)
        else:
            exc_info = kw.pop("exc_info", False)
            self._log.error(self._fmt(event, **kw), exc_info=exc_info)

    def critical(self, event: str, *args, **kw):
        if args:
            self._log.critical(event, *args)
        else:
            self._log.critical(self._fmt(event, **kw))


def configure_logging() -> None:
    """全局日志配置:应用启动时调用一次(重复调用安全)。"""
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    # 清掉可能存在的旧 handler(测试/重载场景防重复)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        # 日志文件写不了不阻塞应用(只影响落盘)
        root.warning("logger.file_handler_unavailable")

    # 压低第三方库噪音
    for noisy in ("httpx", "httpcore", "openai", "sqlalchemy.engine", "sqlalchemy.pool", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> _Logger:
    """每个模块:logger = get_logger(__name__)。"""
    return _Logger(name)
