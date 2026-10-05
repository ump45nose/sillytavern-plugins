ARG MCP_RUNTIME_IMAGE=python:3.12-slim
FROM ${MCP_RUNTIME_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER root
WORKDIR /app
# 部署端只注入已固定提交和校验摘要的 wheel；不把 Git 凭据加入构建。
COPY wheels/ /wheels/
# 基础镜像复用 CRM 的依赖环境；只在新镜像层移除其旧业务分发包。
RUN python -m pip uninstall -y personal-crm \
    && python -m pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
    && python -m pip check
COPY src/ /app/src/
ENV PYTHONPATH=/app/src
EXPOSE 8080
USER 1000:1001
ENTRYPOINT []
CMD ["python", "-c", "from usage_monitor_mcp.server import main; main()"]
