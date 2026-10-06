#!/usr/bin/env bash
set -euo pipefail
task_repo=$(cd "$(dirname "$0")/.." && pwd)
task_stage=$(mktemp -d)
trap 'rm -rf "$task_stage"' EXIT
task_base=${HUB_BASE_IMAGE:-local/personal-crm:events-runtime-0.1.5-f8f818fd3723}
task_image=${HUB_IMAGE:-local/personal-data-hub:0.1.0}
cd "$task_repo"
uv build --wheel --out-dir "$task_stage/wheels"
uv build --wheel --package personal-crm --out-dir "$task_stage/wheels"
# 私有 Git 依赖已在现有锁定基础镜像中；构建上下文只包含 wheel 和非秘密依赖。
cat > "$task_stage/Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY wheels /tmp/hub-wheels
RUN uv pip install --system 'psycopg[binary]==3.3.6' && uv pip install --system --no-deps /tmp/hub-wheels/*.whl && rm -rf /tmp/hub-wheels
CMD ["personal-data-hub"]
EOF
docker inspect "$task_base" --format '{{.Id}}'
docker build --build-arg "BASE_IMAGE=$task_base" --tag "$task_image" "$task_stage"
