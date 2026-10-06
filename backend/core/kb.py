# backend/core/kb.py
# 知识库:文档分块(纯函数)+ BGE-M3 本地嵌入(惰性单例)+ pgvector 余弦检索。
# 权重默认走本地路径(见 config.kb_embedding_model_path),CPU 推理。

from __future__ import annotations

import re
import threading

from sqlalchemy import select

from backend.config import get_settings
from backend.core.logger import get_logger
from backend.db import models as M
from backend.db.base import get_sessionmaker

logger = get_logger(__name__)

_model = None
_model_lock = threading.Lock()


def get_embedder():
    """BGE-M3 惰性加载(线程安全单例;首次约 1~2 分钟,CPU)。"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                import torch
                from FlagEmbedding import BGEM3FlagModel

                path = get_settings().kb_embedding_model_path
                logger.info("kb.embedder_loading", path=path)
                _model = BGEM3FlagModel(model_name_or_path=path, use_fp16=torch.cuda.is_available())
                logger.info("kb.embedder_loaded")
    return _model


def embed_texts(texts: list[str], batch_size: int = 8) -> list[list[float]]:
    out = get_embedder().encode(
        texts, batch_size=batch_size, max_length=1024,
        return_dense=True, return_sparse=False, return_colbert_vecs=False,
    )
    vecs = out["dense_vecs"].tolist()
    for v in vecs:
        if len(v) != 1024:
            raise RuntimeError(f"嵌入维度异常:{len(v)}(应为 1024)")
    return vecs


def embed_query(text: str) -> list[float]:
    return embed_texts([text], batch_size=1)[0]


def chunk_markdown(title: str, content: str, min_len: int = 60) -> list[dict]:
    """按 `## ` 小标题切块(块标题 = 文档标题 · 小节标题);过短块合并到上一块。纯函数可单测。"""
    parts: list[dict] = []
    cur_title = title
    cur_lines: list[str] = []

    def _flush():
        text = "\n".join(cur_lines).strip()
        if text:
            parts.append({"title": cur_title, "content": text})

    for line in content.splitlines():
        if line.startswith("## "):
            _flush()
            cur_title = f"{title} · {line[3:].strip()}"
            cur_lines = []
        elif line.startswith("# "):
            continue
        else:
            cur_lines.append(line)
    _flush()

    merged: list[dict] = []
    for p in parts:
        if merged and len(p["content"]) < min_len:
            merged[-1]["content"] = merged[-1]["content"] + "\n" + p["content"]
        else:
            merged.append(p)
    return [p for p in merged if p["content"]]


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s,。?!、;:()\"'~…]+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def rerank(query: str, items: list[dict], top_k: int) -> list[dict]:
    """轻量混合重排:向量分 + 标题/内容关键词(bigram)重合加权。
    标题权重更高(短且判别性强),内容只看前 200 字避免长文本饱和。纯函数可单测。"""
    q = _bigrams(query)
    qn = max(len(q), 1)
    out: list[dict] = []
    for it in items:
        title_overlap = len(q & _bigrams(str(it.get("title") or ""))) / qn
        content_overlap = len(q & _bigrams(str(it.get("content") or "")[:200])) / qn
        score = float(it.get("score") or 0) + 0.25 * title_overlap + 0.05 * content_overlap
        out.append({**it, "score": round(score, 4)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]


async def search_kb(query: str, top_k: int | None = None) -> list[dict]:
    """pgvector 余弦检索 + 轻量混合重排;返回 [{title(小节级), doc, content, score}]。"""
    k = top_k or get_settings().kb_top_k
    vec = embed_query(query)
    async with get_sessionmaker()() as session:
        dist = M.KbChunk.embedding.cosine_distance(vec).label("dist")
        rows = (
            await session.execute(
                select(M.KbChunk.content, M.KbChunk.meta, M.KbDoc.title, dist)
                .join(M.KbDoc, M.KbDoc.id == M.KbChunk.doc_id)
                .where(M.KbChunk.embedding.isnot(None))
                .order_by(dist)
                .limit(max(k * 3, 12))
            )
        ).all()
        candidates = []
        for content, meta, doc_title, d in rows:
            chunk_title = (meta or {}).get("title") if isinstance(meta, dict) else None
            candidates.append({
                "title": chunk_title or doc_title,
                "doc": doc_title,
                "content": content,
                "score": round(1.0 - float(d), 4),
            })
    return rerank(query, candidates, k)
