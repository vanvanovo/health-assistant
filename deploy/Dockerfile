# deploy/Dockerfile — 核心镜像(gateway;RAG 用 Dockerfile.rag,前端单独构建)
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DEFAULT_TIMEOUT=120

COPY deploy/requirements-core.txt ./requirements-core.txt
RUN pip install --no-cache-dir -r requirements-core.txt

COPY backend ./backend
COPY services ./services
COPY scripts ./scripts
COPY deploy/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8020
ENTRYPOINT ["./entrypoint.sh"]
