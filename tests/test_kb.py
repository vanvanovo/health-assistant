# tests/test_kb.py
# 知识库分块 / 混合重排纯函数用例。

from backend.core.kb import chunk_markdown, rerank


def test_chunk_by_section_heading():
    content = """# 睡眠基础

## 睡眠时长需求

成年人需要每晚 7~9 小时睡眠,长期少于 6 小时会影响恢复与情绪,建议规律作息并观察白天状态。

## 咖啡因与酒精

咖啡因作用可持续 6 小时以上,建议下午 2 点后不摄入咖啡与浓茶。
"""
    chunks = chunk_markdown("睡眠基础", content, min_len=20)
    assert len(chunks) == 2
    assert chunks[0]["title"] == "睡眠基础 · 睡眠时长需求"
    assert "7~9 小时" in chunks[0]["content"]
    assert chunks[1]["title"] == "睡眠基础 · 咖啡因与酒精"


def test_short_chunk_merged_into_previous():
    content = """# 测试

## 第一节

这是一段足够长的正文内容,用来避免被合并,描述一些具体的建议与做法。

## 第二节

短。
"""
    chunks = chunk_markdown("测试", content)
    assert len(chunks) == 1
    assert "短。" in chunks[0]["content"]


def test_doc_title_line_skipped_but_used_as_prefix():
    content = "# 大标题\n\n## 小节\n\n" + "内容" * 40
    chunks = chunk_markdown("大标题", content)
    assert chunks[0]["title"] == "大标题 · 小节"
    assert not chunks[0]["content"].startswith("#")


def test_empty_content_returns_no_chunks():
    assert chunk_markdown("空", "") == []


def test_rerank_boosts_title_match():
    items = [
        {"title": "运动训练基础原则 · 渐进超负荷", "content": "每周加量不超过 10%。", "score": 0.60},
        {"title": "运动训练基础原则 · 强度怎么把握", "content": "谈话测试与 RPE 两种方法。", "score": 0.52},
    ]
    top = rerank("运动强度怎么把握才算合适", items, top_k=1)
    assert len(top) == 1
    assert "强度怎么把握" in top[0]["title"]


def test_rerank_respects_top_k_and_keeps_fields():
    items = [
        {"title": f"条目{i}", "content": "内容", "score": 0.5 - i * 0.01} for i in range(5)
    ]
    top = rerank("查无匹配字样的问句", items, top_k=3)
    assert len(top) == 3
    assert all({"title", "content", "score"} <= set(t) for t in top)
