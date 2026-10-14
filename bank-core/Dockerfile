FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# 依赖层单独 COPY，利用构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 业务代码（models/routers/scheduler/seed 全在 app/ 内）
COPY app/ ./app/
# 与 deploy/docker-compose.yml 的 environment 对齐（DB_PATH=/app/data/bank.db）
ENV DB_PATH=/app/data/bank.db
# 非 root 运行：先建用户与数据目录并授权，否则 SQLite 建库 PermissionError；
# 命名卷 bank-data:/app/data 首次挂载会继承镜像内 /app/data 的属主（appuser），权限闭环
RUN useradd -m -u 10001 appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
