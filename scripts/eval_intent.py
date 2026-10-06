# scripts/eval_intent.py
# 意图路由评测:读 data/intent_eval.jsonl,逐条真实调用 route_intent,统计集合匹配准确率。
# 用法:python scripts/eval_intent.py [--limit N] [--out docs/intent_eval_report.md]

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import asyncio  # noqa: E402

from backend.core.logger import configure_logging  # noqa: E402
from backend.core.router import route_intent  # noqa: E402

DATASET = os.path.join(BASE_DIR, "data", "intent_eval.jsonl")


async def run(limit: int | None) -> int:
    configure_logging()
    rows = [json.loads(line) for line in open(DATASET, encoding="utf-8") if line.strip()]
    if limit:
        rows = rows[:limit]
    print(f"dataset: {len(rows)} 条")

    total = 0
    exact = 0
    by_label_total: Counter = Counter()
    by_label_hit: Counter = Counter()
    confusions: Counter = Counter()
    failures = []

    for i, row in enumerate(rows, 1):
        text = row["text"]
        expected = sorted(set(row["expected"]))
        # 等价口径:边界 phrasing 允许多种合理输出(如"出差"是否单独记事件)
        alternatives = [sorted(set(a)) for a in (row.get("expected_any") or [])]
        accepted = {tuple(expected)} | {tuple(a) for a in alternatives}
        try:
            routed = await route_intent(text)
            actual = sorted({it["name"] for it in routed["intents"]})
        except Exception as e:  # noqa: BLE001
            actual = [f"ERROR:{type(e).__name__}"]
        total += 1
        label = "multi" if len(expected) > 1 else expected[0]
        by_label_total[label] += 1
        if tuple(actual) in accepted:
            exact += 1
            by_label_hit[label] += 1
        else:
            failures.append((text, expected, actual))
            if len(expected) == 1:
                confusions[f"{expected[0]} → {actual[0] if actual else '-'}"] += 1
        if i % 10 == 0:
            print(f"  ... {i}/{len(rows)}")

    acc = exact / total if total else 0
    print("\n===== 意图评测报告 =====")
    print(f"集合完全匹配准确率: {exact}/{total} = {acc:.1%}")
    print("\n分类别:")
    for label in ("record", "checkin", "analyze", "plan", "out_of_scope", "multi"):
        if by_label_total[label]:
            print(f"  {label:12s}: {by_label_hit[label]}/{by_label_total[label]} = {by_label_hit[label]/by_label_total[label]:.1%}")
    if confusions:
        print("\n单意图混淆(期望 → 实际):")
        for k, v in confusions.most_common():
            print(f"  {k}: {v}")
    if failures:
        print(f"\n失败样本({len(failures)} 条,最多列 15):")
        for text, exp, act in failures[:15]:
            print(f"  · {text}\n    期望={exp} 实际={act}")

    out_path = _parse_out_arg()
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# 意图路由评测报告(P4 冷启动)\n\n")
            f.write(f"- 数据集:{len(rows)} 条(正常/模糊/越界/多意图)\n")
            f.write(f"- **集合完全匹配准确率:{exact}/{total} = {acc:.1%}**\n\n")
            f.write("| 类别 | 命中 |\n|---|---|\n")
            for label in ("record", "checkin", "analyze", "plan", "out_of_scope", "multi"):
                if by_label_total[label]:
                    f.write(f"| {label} | {by_label_hit[label]}/{by_label_total[label]} = {by_label_hit[label]/by_label_total[label]:.1%} |\n")
            if confusions:
                f.write("\n## 单意图混淆\n\n")
                for k, v in confusions.most_common():
                    f.write(f"- {k}: {v}\n")
            if failures:
                f.write("\n## 失败样本(最多 15 条)\n\n")
                for text, exp, act in failures[:15]:
                    f.write(f"- 「{text}」 期望 `{exp}` 实际 `{act}`\n")
        print(f"\n报告已写入:{out_path}")
    return 0 if acc >= 0.8 else 1


def _parse_out_arg() -> str | None:
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=str, default=None)
    args, _ = parser.parse_known_args()
    return asyncio.run(run(args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
