FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY . /app
# 使用提交的锁文件复现 Python 3.12 生产依赖。
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
EXPOSE 8080
# 迁移由部署步骤显式执行，容器启动不自动改库
CMD ["uv", "run", "--no-dev", "personal-crm-server"]
