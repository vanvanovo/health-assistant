# scripts/build_kb.py
# P9:幂等重建健康知识库(data/kb/*.md → 按小节分块 → BGE-M3 嵌入 → kb_docs/kb_chunks)。
# 用法:python scripts/build_kb.py   (首次会加载 BGE-M3,CPU 约 1~2 分钟)

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import asyncio  # noqa: E402

from sqlalchemy import delete, func, select  # noqa: E402

from backend.core.kb import chunk_markdown, embed_texts  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402
from backend.db import models as M  # noqa: E402
from backend.db.base import dispose_engine, get_sessionmaker  # noqa: E402

KB_DIR = os.path.join(BASE_DIR, "data", "kb")


def _read_doc(fn: str) -> tuple[str, str]:
    text = open(os.path.join(KB_DIR, fn), encoding="utf-8").read()
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), fn[:-3])
    return title, text


async def main() -> int:
    configure_logging()
    if not os.path.isdir(KB_DIR):
        print(f"FAIL: 语料目录不存在:{KB_DIR}")
        return 1
    files = sorted(f for f in os.listdir(KB_DIR) if f.endswith(".md"))
    if not files:
        print("FAIL: 没有 .md 语料")
        return 1

    chunks: list[dict] = []
    for fn in files:
        title, text = _read_doc(fn)
        for c in chunk_markdown(title, text):
            chunks.append({"doc": fn, "title": c["title"], "content": c["content"]})
    print(f"docs: {len(files)} | chunks: {len(chunks)}")

    print("embedding(CPU;首次加载 BGE-M3 约 1~2 分钟)…")
    vecs = embed_texts([c["content"] for c in chunks])
    if len(vecs) != len(chunks):
        print("FAIL: 嵌入数量不一致")
        return 1

    async with get_sessionmaker()() as session:
        await session.execute(delete(M.KbChunk))
        await session.execute(delete(M.KbDoc))
        await session.commit()

        doc_ids: dict[str, int] = {}
        for fn in files:
            title, text = _read_doc(fn)
            doc = M.KbDoc(title=title, category=fn.split("-")[0], content=text)
            session.add(doc)
            await session.flush()
            doc_ids[fn] = doc.id

        per_no: dict[str, int] = {}
        for c, vec in zip(chunks, vecs):
            per_no[c["doc"]] = per_no.get(c["doc"], 0) + 1
            session.add(M.KbChunk(
                doc_id=doc_ids[c["doc"]], chunk_no=per_no[c["doc"]],
                content=c["content"], embedding=vec, meta={"title": c["title"]},
            ))
        await session.commit()

        docs_n = (await session.execute(select(func.count()).select_from(M.KbDoc))).scalar_one()
        chunks_n = (await session.execute(select(func.count()).select_from(M.KbChunk))).scalar_one()

    await dispose_engine()
    print(f"BUILD KB DONE: docs={docs_n} chunks={chunks_n}")
    print("BUILD KB PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
