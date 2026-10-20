FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.16 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY dist/requirements.txt /tmp/requirements.txt
COPY dist/wheels/ /tmp/wheels/
RUN uv pip install --system --no-cache -r /tmp/requirements.txt /tmp/wheels/*.whl \
    && uv pip check --system && rm -rf /tmp/wheels /tmp/requirements.txt
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=8).read()"
CMD ["personal-crm-server"]
