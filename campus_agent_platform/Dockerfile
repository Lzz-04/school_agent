# 后端运行时镜像（多阶段：前端在 node 阶段构建后并入 static/，单容器单端口部署）
# 构建上下文 = 项目根（含 campus_agent_platform/ 与 campus-agent-frontend/）

# ---------- 阶段 1：前端构建 ----------
FROM node:20-alpine AS fe
WORKDIR /fe
COPY campus-agent-frontend/package.json campus-agent-frontend/package-lock.json ./
RUN npm ci
COPY campus-agent-frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端运行 ----------
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAMPUS_AGENT_DB_PATH=/app/data/campus_agent.db

COPY campus_agent_platform/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY campus_agent_platform/ /app/campus_agent_platform/
# 前端产物由后端统一托管（/static 挂载 + index.html 回退）
COPY --from=fe /fe/dist/ /app/campus_agent_platform/static/

EXPOSE 8000
VOLUME ["/app/data"]
CMD ["python", "-m", "campus_agent_platform.main", "api", "--host", "0.0.0.0", "--port", "8000"]
