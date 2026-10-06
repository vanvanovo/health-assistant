# 个人健康助手(health-assistant)

> 简历项目三:基于 LangGraph 的个人健康管理助手 —— 从「一问一答」到「记录 → 分析 → 计划 → 打卡 → 反馈调整」的长期闭环 + 主动服务 + 数据看板。

## 进度

- **V1 核心闭环 MVP ✅ 完成(2026-10-06,P0–P4)**:14 表数据底座(pgvector)/ MCP 四域 15 工具 / 记录·分析·计划三张 LangGraph 图 / 编排 + SSE / Vue3 工作台初版 / 意图评测 60/60
- **V2 个性化与可视化 ✅ 完成(P5–P7)**:饮食双模式 / PostgresSaver 多轮记忆 + 记忆确认卡 / 画像页 / 热力图·四维雷达·完成率环形·对话联动高亮
- **V3 主动服务与知识问答 ✅ 完成(P8–P9)**:提醒/简报/周报/预警 + 站内信 / 健康知识 RAG(A2A 独立服务 :5021)+ 安全边界(高危双层拦截)
- V4 实施计划已出(**核心完成**):P10 加固 ✅ + P11 本机交付 ✅(Docker 一键起已验证,http://localhost:8080);⏸ 演示脚本·录屏暂缓;⏳ 云端轻量待服务器信息

## 核心指标(全部实测,可复现;详见 docs/ 验收记录与评测报告)

| 指标 | 结果 |
|---|---|
| 离线用例(mock,不烧 token) | **147 passed** |
| 端到端验收 | **39/39**(记录→统计→计划→打卡→饮食→记忆→知识→安全 + 看板/提醒) |
| MCP 工具 | **18 个 / 35 断言全绿**(参数化 + 幂等 + 审计) |
| 三图真实链路(P3) | 12/12 |
| 多轮记忆 | 指代「那这周呢」→ 近 7 天;**重启网关后仍生效**(PostgresSaver) |
| 主动服务 | 四类消息 14/14;预警 6 规则 10 单测;幂等 + 触发前复检 |
| 缓存/写锁(P10) | 看板 **742ms → 3ms**、路由 **2078ms → 1ms**;Redis 关停透明降级 4/4 |
| 意图评测 | 77 条:**100%**(2 条边界项定义等价口径) |
| RAG 评测 | 30 条:命中 **100%** / 来源 **100%** / faithfulness **100%**;检索质量三轮迭代 43.3% → 96.7% → 100% |
| 安全边界 | 12 用例;高危信号 **100% 拦截**、正常不误拦 |
| 演示数据 | 180 天记录 / 8 周计划 / 42 打卡项 / 797 饮食 / 100 营养 / 知识库 8 篇 = 40 块 |
| 模型容灾 | deepseek-v4-pro 主 → flash 备(空正文视同失败,切换实测) |
| 单次响应(思考关闭) | 记录 ~2s · 统计 ~2.3s · 计划 ~6.7s · 知识问答 ~7.7s(本地 CPU 检索) |

## 快速开始(本机)

```powershell
$py = "C:\Users\97916\.conda\envs\Edu_Agent\python.exe"

# 方式 A:一键起(Docker:gateway :8020 + frontend http://localhost:8080 + postgres)
docker compose up -d --build
docker compose --profile v4 up -d redis        # 可选:缓存/写锁(不启也透明降级)

# 方式 B(开发/手动):
# 1) 基础设施(PG + pgvector :5434)
docker compose up -d postgres

# 2) 首次初始化(建表 + 演示数据)
& $py scripts\init_db.py
& $py scripts\gen_demo_data.py

# 2.5) Redis(P10:看板缓存/路由缓存/写锁;不启动也能跑——自动透明降级)
docker compose --profile v4 up -d redis

# 3) 网关(:8020;run_server.py 会在 Windows 上先切 Selector 事件循环,psycopg 需要)
& $py run_server.py

# 4) 知识库(首次:RAG Agent 需要先建库)
& $py scripts\build_kb.py                 # 语料 → 分块 → BGE-M3 嵌入 → pgvector
Start-Process $py -ArgumentList "services\rag_agent\server.py"   # A2A :5021(独立进程)

# 5) 前端(:3020,演示账号 health-demo / health-demo)
cd frontend; npm install; npm run dev
```

## 验收脚本(可复现)

| 脚本 | 对象 |
|---|---|
| `scripts/check_llm.py` | P0 LLM 主备冒烟(含降级链) |
| `scripts/check_data.py` | P1 数据底座断言 |
| `scripts/check_health_mcp.py` | P2 MCP **18 工具**(35 断言,结束自动复原数据) |
| `scripts/check_agents.py` | P3 三图真实链路(12 断言) |
| `scripts/check_e2e.py` | 端到端(**39 断言**:SSE/看板/饮食/记忆/知识/安全/主动服务/鉴权) |
| `scripts/check_diet.py` | P5 饮食真实链路(10 断言) |
| `scripts/check_memory.py phase1\|phase2` | P6 多轮指代 + 重启记忆(phase1 后请重启网关再跑 phase2) |
| `scripts/check_notify.py` | P8 主动服务(14 断言:四类消息/幂等/已读流转) |
| `scripts/check_rag.py phase1\|phase2` | P9 RAG 问答与降级(phase1 后停 Agent 再跑 phase2);`scripts/eval_rag.py` RAG 评测 |
| `scripts/check_cache.py phase1\|phase2` | P10 缓存命中/写锁/Redis 关停降级(phase1 后停 Redis 再跑 phase2) |
| `scripts/demo_reset.py` | **一键复原演示环境**(重灌数据 + 清会话记忆 + 清缓存) |
| `scripts/eval_intent.py` | 意图评测(**77 条**,报告落 docs/) |
| `python -m pytest -q tests` | 离线回归(**147 用例**,全 mock) |

## 文档

- 方案:`docs/个人健康助手总体方案与流程图.md`(已评审)
- 计划:`docs/个人健康助手V1~V4实施计划.md`
- 验收:`docs/p0~p10_验收记录.md`
- 评测:`docs/p4_意图评测报告.md`、`docs/p6_意图评测报告.md`、`docs/p9_rag评测报告.md`
- 面试:`docs/简历口径与面试卡.md`(简历描述 / 60 秒开场白 / 高频追问 10 问)
- ⏸ 暂缓:`docs/演示脚本.md`(按需求后补)

## 参考(只读)与纪律

- 参考:`D:\work\health-planner`(业务原型与数据资产)/ `EduAgent_Pro`(工程骨架)/ `D:\work\cs-platform`(A2A RAG / MCP / SSE / 前端)/ `SmartVoyage`(协议样例)/ `D:\work\office-agent`(口径)
- 纪律:未实测指标不虚报;密钥不进 Git;健康数据按个人敏感信息对待(公网仅演示数据)
