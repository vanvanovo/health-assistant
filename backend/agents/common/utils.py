# backend/agents/common/utils.py

from __future__ import annotations

import hashlib


def short_hash(text: str, length: int = 8) -> str:
    """稳定短哈希(用于幂等键;同输入同 key,重放可去重)。"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:length]


WEEKDAY_CN = "一二三四五六日"


def weekday_cn(d) -> str:
    """date → 周X。"""
    return f"周{WEEKDAY_CN[d.weekday()]}"
