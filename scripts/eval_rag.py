# scripts/eval_rag.py
# P9:RAG 评测(30 问答对)— 检索命中率 / 来源率 / faithfulness 抽样(LLM-Judge)。
# 前置:RAG Agent 已启动(python services/rag_agent/server.py)。
# 用法:python scripts/eval_rag.py [--limit N] [--judge N] [--out docs/p9_rag评测报告.md]

import argparse
import asyncio
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from backend.agents.common import llm_json  # noqa: E402
from backend.core.a2a_client import call_health_rag  # noqa: E402
from backend.core.logger import configure_logging  # noqa: E402

DATASET = os.path.join(BASE_DIR, "data", "rag_eval.jsonl")


async def _judge(question: str, sources: list[dict], answer: str) -> dict:
    ctx = "\n\n".join(f"【{s.get('title')}】{s.get('snippet', '')}" for s in sources)
    return await llm_json.chat_json(
        [
            {
                "role": "system",
                "content": (
                    "你是评测员。判断【助手回答】是否完全基于【知识来源】,没有编造来源之外的信息,"
                    '也没有违反"不诊断不开药"。只输出严格 JSON:{"score": 0 或 1, "reason": "一句话"}'
                ),
            },
            {"role": "user", "content": f"问题:{question}\n\n知识来源:\n{ctx}\n\n助手回答:\n{answer}"},
        ],
        temperature=0,
    )


async def main(limit: int | None, judge_n: int, out_path: str | None) -> int:
    configure_logging()
    rows = [json.loads(line) for line in open(DATASET, encoding="utf-8") if line.strip()]
    if limit:
        rows = rows[:limit]
    print(f"dataset: {len(rows)} 条(RAG Agent 需已启动)")

    hits = sources_n = 0
    failures: list[tuple[str, str]] = []
    collected: list[dict] = []

    for i, row in enumerate(rows, 1):
        q = row["q"]
        try:
            data = await call_health_rag(q)
        except Exception as e:  # noqa: BLE001
            failures.append((q, f"调用失败:{type(e).__name__}: {e}"))
            continue
        src = data.get("sources") or []
        titles = [str(s.get("title") or "") for s in src]
        hit = any(any(k in t for t in titles) for k in row["keywords"])
        hits += 1 if hit else 0
        sources_n += 1 if src else 0
        if not hit:
            failures.append((q, f"未命中期望主题,sources={titles[:3]}"))
        collected.append({"q": q, "answer": data.get("answer") or "", "sources": src, "hit": hit, "mode": data.get("answer_mode")})
        if i % 5 == 0:
            print(f"  ... {i}/{len(rows)}")

    n = len(rows)
    hit_rate = hits / n if n else 0
    source_rate = sources_n / n if n else 0

    sampled = [c for c in collected if c["hit"]][:judge_n]
    judge_pass = 0
    judge_details = []
    for c in sampled:
        try:
            verdict = await _judge(c["q"], c["sources"], c["answer"])
            score = int(verdict.get("score") or 0)
        except Exception as e:  # noqa: BLE001
            score, verdict = 0, {"reason": f"judge失败:{e}"}
        judge_pass += 1 if score == 1 else 0
        judge_details.append((c["q"], score, str(verdict.get("reason") or "")[:60]))
    faith = judge_pass / len(sampled) if sampled else 0

    print("\n===== RAG 评测报告 =====")
    print(f"检索命中率: {hits}/{n} = {hit_rate:.1%}")
    print(f"来源率:     {sources_n}/{n} = {source_rate:.1%}")
    print(f"faithfulness(抽样 {len(sampled)}): {judge_pass}/{len(sampled)} = {faith:.1%}")
    if failures:
        print(f"\n未命中({len(failures)} 条):")
        for q, why in failures[:10]:
            print(f"  · {q} — {why}")

    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# RAG 评测报告(P9)\n\n")
            f.write(f"- 数据集:data/rag_eval.jsonl 共 {n} 条;检索后端:pgvector + BGE-M3(本地 CPU)\n")
            f.write(f"- **检索命中率:{hits}/{n} = {hit_rate:.1%}**(来源标题命中期望主题)\n")
            f.write(f"- **来源率:{sources_n}/{n} = {source_rate:.1%}**\n")
            f.write(f"- **faithfulness 抽样(LLM-Judge,{len(sampled)} 条):{judge_pass}/{len(sampled)} = {faith:.1%}**\n\n")
            if judge_details:
                f.write("## faithfulness 抽样明细\n\n| 问题 | 判定 | 理由 |\n|---|---|---|\n")
                for q, s, r in judge_details:
                    f.write(f"| {q} | {'✅' if s else '❌'} | {r} |\n")
            if failures:
                f.write("\n## 未命中样例\n\n")
                for q, why in failures[:10]:
                    f.write(f"- {q} — {why}\n")
        print(f"\n报告已写入:{out_path}")
    return 0 if hit_rate >= 0.8 else 1


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--judge", type=int, default=10)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()
    return asyncio.run(main(args.limit, args.judge, args.out))


if __name__ == "__main__":
    raise SystemExit(cli())
