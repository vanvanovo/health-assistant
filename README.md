# 个人健康助手(health-assistant)

> 简历项目三:基于 LangGraph 的个人健康管理助手 —— 从「一问一答」到「记录 → 分析 → 计划 → 打卡 → 反馈调整」的长期闭环 + 主动服务 + 数据看板。

## 进度

- **V1 核心闭环 MVP ✅ 完成(2026-10-06,P0–P4)**:14 表数据底座(pgvector)/ MCP 四域 15 工具 / 记录·分析·计划三张 LangGraph 图 / 编排 + SSE / Vue3 工作台初版 / 意图评测 60/60
- V2 实施计划已出(**进行中**):P5 饮食 Agent ✅(记录估算 + 食谱推荐)→ P6 画像与长期记忆 → P7 可视化深化

## 快速开始(本机)

```powershell
$py = "C:\Users\97916\.conda\envs\Edu_Agent\python.exe"

# 1) 基础设施(PG + pgvector :5434)
docker compose up -d postgres

# 2) 首次初始化(建表 + 演示数据)
& $py scripts\init_db.py
& $py scripts\gen_demo_data.py

# 3) 网关(:8020)
& $py -m uvicorn backend.main:app --host 0.0.0.0 --port 8020

# 4) 前端(:3020,演示账号 health-demo / health-demo)
cd frontend; npm install; npm run dev
```

## 验收脚本(可复现)

| 脚本 | 对象 |
|---|---|
| `scripts/check_llm.py` | P0 LLM 主备冒烟(含降级链) |
| `scripts/check_data.py` | P1 数据底座断言 |
| `scripts/check_health_mcp.py` | P2 MCP 15 工具(35 断言,结束自动复原数据) |
| `scripts/check_agents.py` | P3 三图真实链路(12 断言) |
| `scripts/check_e2e.py` | P4 端到端(20 断言:SSE/看板/打卡/鉴权) |
| `scripts/eval_intent.py` | 意图评测(60 条,报告落 docs/) |
| `python -m pytest -q tests` | 离线回归(61 用例,全 mock) |

## 文档

- `docs/个人健康助手总体方案与流程图.md`(已评审)
- `docs/个人健康助手V1实施计划.md`(V1 完成)
- `docs/p0~p4_验收记录.md`、`docs/p4_意图评测报告.md`

## 参考(只读)与纪律

- 参考:`D:\work\health-planner`(业务原型与数据资产)/ `EduAgent_Pro`(工程骨架)/ `D:\work\cs-platform`(A2A RAG / MCP / SSE / 前端)/ `SmartVoyage`(协议样例)/ `D:\work\office-agent`(口径)
- 纪律:未实测指标不虚报;密钥不进 Git;健康数据按个人敏感信息对待(公网仅演示数据)
