# Build the pinned upstream source prepared by prepare.py; keep its official runtime identity.
FROM ghcr.io/subboost/subboost@sha256:01f7d8e02486bf536e4da0fee2ce1dd1003294460cfeeb2c64d4295c7d0f4def AS builder
USER root
WORKDIR /package
COPY package.json package-lock.json ./
COPY packages ./packages
COPY local/package.json local/package.json
RUN --mount=type=cache,target=/root/.npm,sharing=locked npm ci --include=dev --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS=--max-old-space-size=1536
ENV APP_RELEASE_VERSION=2.8.1
ENV APP_BUILD_SHA=4a69b494b46d095c965be58cf425fe35a2c1e524
ENV APP_VERSION=2.8.1+sha.4a69b494b46d.tailnet.1
ENV APP_VERSION_TOKEN=2.8.1+sha.4a69b494b46d.tailnet.1
RUN npx vitest run local/src/lib/android-tailscale.test.ts 'local/app/api/subscriptions/[id]/config.yaml/route.test.ts'
RUN npm --workspace @subboost/local run build

FROM ghcr.io/subboost/subboost@sha256:01f7d8e02486bf536e4da0fee2ce1dd1003294460cfeeb2c64d4295c7d0f4def
COPY --chown=node:node --from=builder /package/local/.next/standalone /app/
COPY --chown=node:node --from=builder /package/local/.next/static /app/local/.next/static
ENV APP_VERSION=2.8.1+sha.4a69b494b46d.tailnet.1
ENV APP_VERSION_TOKEN=2.8.1+sha.4a69b494b46d.tailnet.1
LABEL org.opencontainers.image.source="https://github.com/ump45nose/app-configs"
LABEL local.subboost.upstream="4a69b494b46d095c965be58cf425fe35a2c1e524"
LABEL local.subboost.profile="android-tailscale-v1"
