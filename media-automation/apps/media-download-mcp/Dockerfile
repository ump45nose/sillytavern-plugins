FROM python:3.12-slim
WORKDIR /build
COPY packages/media-capabilities/ /build/media-capabilities/
RUN pip wheel --no-deps --wheel-dir /wheels /build/media-capabilities
COPY apps/media-download-mcp/requirements.lock /build/requirements.lock
RUN pip install --no-cache-dir --find-links /wheels -r /build/requirements.lock
COPY apps/media-download-mcp/ /build/media-download-mcp/
RUN pip install --no-deps /build/media-download-mcp
EXPOSE 8091
CMD ["media-download-mcp", "--config", "/config/config.json", "--transport", "streamable-http"]
