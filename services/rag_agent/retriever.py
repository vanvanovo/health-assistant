# services/rag_agent/retriever.py
# 检索后端:pgvector(默认);检索失败返回空 → server 走 llm_direct 降级(可插拔预留 Milvus/none)。

from __future__ import annotations

from backend.core import kb
from backend.core.logger import get_logger

logger = get_logger(__name__)


async def retrieve_docs(query: str, top_k: int = 4) -> dict:
    """返回 {docs: [{title, content, score}], mode}。"""
    try:
        docs = await kb.search_kb(query, top_k=top_k)
        return {"docs": docs, "mode": "pgvector"}
    except Exception as e:  # noqa: BLE001
        logger.warning("retriever.failed", error=str(e)[:200])
        return {"docs": [], "mode": "none"}
