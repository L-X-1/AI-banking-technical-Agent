FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
# 与 compose 对齐；LLM_API_KEY 由 compose 注入（${LLM_API_KEY}），缺省为空 = 规则降级路
ENV BANK_CORE_URL=http://bank-core:8100 LLM_API_KEY="" LLM_PROVIDER=deepseek LLM_MODEL=deepseek-chat
# 非 root 运行：先建用户与数据目录并授权，否则 agent.db 建库 PermissionError；
# 命名卷 agent-data:/app/data 首次挂载继承镜像内 /app/data 属主（appuser），权限闭环
RUN useradd -m -u 10001 appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
