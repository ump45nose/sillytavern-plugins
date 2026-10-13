FROM node:22-alpine AS ui
WORKDIR /ui
COPY apps/media-search/frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY apps/media-search/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /build
COPY packages/media-capabilities/ /build/media-capabilities/
RUN pip wheel --no-deps --wheel-dir /wheels /build/media-capabilities
COPY apps/media-search/requirements.lock /build/requirements.lock
RUN pip install --no-cache-dir --find-links /wheels -r /build/requirements.lock
COPY apps/media-search/ /build/media-search/
COPY --from=ui /media_search/static/ /build/media-search/media_search/static/
RUN pip install --no-deps /build/media-search
EXPOSE 8090
CMD ["media-search", "--config", "/config/config.json"]
