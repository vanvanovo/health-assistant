# services/rag_agent/server.py
# 独立「健康知识」RAG A2A Agent(P9)
#
# 定位:把知识库检索+回答能力独立成 A2A 服务——知识库升级/故障不影响主链路,主控只降级。
#   - 对外:A2A 协议(AgentCard 能力发现 + Task 状态机)
#   - 对内:检索后端 pgvector(可插拔);安全边界(高危先拦,不生成任何建议)
#   - 前置于生成前:命中高危 → answer_mode=safety,直接给就医/急救引导
#
# 运行:python services/rag_agent/server.py     → http://localhost:5021
# 主控调用:backend/core/a2a_client.py::call_health_rag

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python_a2a import (  # noqa: E402
    A2AServer,
    AgentCard,
    AgentSkill,
    Task,
    TaskState,
    TaskStatus,
    run_server,
)

from backend.config import get_settings  # noqa: E402
from backend.core import safety  # noqa: E402
from backend.core.llm import get_llm_client  # noqa: E402
from backend.core.logger import configure_logging, get_logger  # noqa: E402
from services.rag_agent.retriever import retrieve_docs  # noqa: E402

logger = get_logger(__name__)

AGENT_NAME = "HealthKnowledgeAgent"
AGENT_DESCRIPTION = "健康知识库 RAG 服务:运动训练 / 营养饮食 / 睡眠恢复 / 安全常识,回答带来源"

SYSTEM = """你是个人健康助手的「健康知识」模块。
硬约束:
1. 只能依据【知识片段】回答;片段里没有的内容不要编造。
2. 不诊断疾病、不开药、不给治疗方案;用户描述症状时建议就医。
3. 语言简洁友好,2~5 句;结尾附一句"仅供参考,不构成医疗建议"。
4. 只输出回答正文,不要标题、不要 JSON。"""


def build_agent_card(port: int) -> AgentCard:
    return AgentCard(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        url=f"http://localhost:{port}",
        version="1.0.0",
        capabilities={"streaming": False, "memory": False},
        skills=[
            AgentSkill(
                name="health_kb_search",
                description="健康知识检索问答(运动/营养/睡眠),回答带来源",
                examples=["晚上睡不好怎么办?", "减脂期怎么吃?"],
            ),
            AgentSkill(
                name="safety_guard",
                description="高危健康信号拦截:只做就医/急救引导,不提供任何建议",
                examples=["我胸痛应该吃什么药"],
            ),
        ],
    )


class HealthRagAgent(A2AServer):
    """A2A 健康知识 Agent:检索 → LLM 生成(带来源/安全边界)。

    工程细节(沿用 cs-platform 已验证做法):服务内常驻事件循环——
    每个请求 asyncio.run() 新建循环会导致共享异步资源(连接池/客户端)绑定在已关闭的循环上;
    统一 run_coroutine_threadsafe 提交到常驻循环。
    """

    def __init__(self, port: int):
        super().__init__(agent_card=build_agent_card(port))
        self._port = port
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        # 预热嵌入模型:避免首个请求冷启动(实测首次 14.5s,贴着 A2A 15s 超时线)
        try:
            asyncio.run_coroutine_threadsafe(self._warmup(), self._loop)
        except Exception:  # noqa: BLE001
            pass

    async def _warmup(self) -> None:
        try:
            from backend.core import kb

            await asyncio.get_running_loop().run_in_executor(None, kb.get_embedder)
            logger.info("rag_agent.warmup_done")
        except Exception as e:  # noqa: BLE001
            logger.warning("rag_agent.warmup_failed", error=str(e)[:120])

    def _run_sync(self, coro, timeout: float = 180.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    async def _handle(self, query: str) -> dict:
        # ① 安全边界:高危信号直接拦截(不检索、不生成)
        risk = safety.check_high_risk(query)
        if risk:
            logger.info("rag_agent.safety_blocked", matched=risk["matched"])
            return {
                "answer": risk["reply"], "sources": [], "answer_mode": "safety",
                "need_clarify": False, "clarify": "",
                "safety": {"level": "high", "matched": risk["matched"]},
            }

        # ② 检索
        ret = await retrieve_docs(query, top_k=get_settings().kb_top_k)
        docs = ret.get("docs") or []
        if docs:
            context = "\n\n".join(f"【{d['title']}】\n{d['content'][:700]}" for d in docs)
            prompt = f"【知识片段】\n{context}\n\n【用户问题】\n{query}\n\n请基于知识片段回答。"
            mode = "rag"
        else:
            prompt = (
                f"【用户问题】\n{query}\n\n"
                "知识库暂时检索不到相关内容;请给出最保守的通用生活方式建议,不要编造具体数字,并明确说明信息有限。"
            )
            mode = "llm_direct"

        # ③ 生成(只引用片段)
        answer = await get_llm_client().achat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.3,
        )
        answer = (answer or "").strip()
        if "仅供参考" not in answer:
            answer += "\n\n仅供参考,不构成医疗建议。"

        sources = [
            {"title": d["title"], "snippet": d["content"][:120], "score": d.get("score")}
            for d in docs
        ]
        # 隐私:不落问答原文(可能含体重等健康数值),只记哈希与长度
        import hashlib as _hashlib

        logger.info(
            "rag_agent.answered",
            query_sha=_hashlib.sha1(query.encode("utf-8")).hexdigest()[:8],
            query_len=len(query),
            mode=mode,
            hits=len(sources),
        )
        return {
            "answer": answer, "sources": sources, "answer_mode": mode,
            "need_clarify": False, "clarify": "", "safety": {"level": "ok"},
        }

    def handle_task(self, task: Task) -> Task:
        try:
            text = (((task.message or {}).get("content") or {}) or {}).get("text", "")
        except Exception:  # noqa: BLE001
            text = ""
        text = (text or "").strip()

        if not text:
            task.status = TaskStatus(state=TaskState.INPUT_REQUIRED)
            task.message = {
                "role": "agent",
                "content": {"text": "请提供要查询的健康问题,例如:晚上睡不好怎么办?"},
            }
            return task

        try:
            result = self._run_sync(self._handle(text))
            task.artifacts = [{"parts": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)
        except Exception as e:  # noqa: BLE001 —— 异常落到 FAILED,别炸服务
            logger.error("rag_agent.failed", error=str(e)[:300])
            task.status = TaskStatus(state=TaskState.FAILED)
            task.message = {"role": "agent", "content": {"text": f"知识库服务异常:{e}"}}
        return task


if __name__ == "__main__":
    configure_logging()
    _port = get_settings().rag_agent_port
    agent = HealthRagAgent(_port)
    print(f"Health Knowledge RAG A2A Agent → http://localhost:{_port}")
    print(f"  AgentCard: {AGENT_NAME} | kb_top_k={get_settings().kb_top_k}")
    run_server(agent, host="0.0.0.0", port=_port)
