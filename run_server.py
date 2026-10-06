# run_server.py
# 本机启动入口(推荐):
#   - Windows: 先切换 Selector 事件循环策略,再启动 uvicorn。
#     psycopg(async)/AsyncPostgresSaver 不支持 Proactor 事件循环;
#     顺序不能反:必须在事件循环创建之前设置,所以不能用 `-m uvicorn`(导入 app 时循环已建好)。
#   - 其他平台:与普通 uvicorn 一致。
# 用法:python run_server.py

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if __name__ == "__main__":
    import uvicorn

    from backend.config import get_settings

    s = get_settings()
    print(f"health-assistant → http://{s.app_host}:{s.app_port}")
    uvicorn.run("backend.main:app", host=s.app_host, port=s.app_port)
