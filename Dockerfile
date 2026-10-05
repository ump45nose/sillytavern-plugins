ARG MCP_RUNTIME_IMAGE=python:3.12-slim
FROM ${MCP_RUNTIME_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# 部署端只注入已固定提交和校验摘要的 wheel；不把 Git 凭据加入构建。
COPY wheels/ /wheels/
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl
COPY src/ /app/src/
ENV PYTHONPATH=/app/src
EXPOSE 8080
CMD ["python", "-c", "from usage_monitor_mcp.server import main; main()"]
