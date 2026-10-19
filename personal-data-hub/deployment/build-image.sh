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
uv build --wheel "$task_repo/../personal-info/personal-records" --out-dir "$task_stage/wheels"
task_runtime_source=${HUB_RUNTIME_SOURCE:-}
if [[ -z "$task_runtime_source" ]]; then
  task_runtime_source=$("$task_repo/.venv/bin/python" - <<'PY'
import os, pwd, subprocess, tomllib
from pathlib import Path
owner_home = Path(pwd.getpwuid(Path('.venv').stat().st_uid).pw_dir)
cache = Path(os.environ.get('UV_CACHE_DIR', str(owner_home / '.cache/uv')))
revision = tomllib.loads(Path('pyproject.toml').read_text())['tool']['uv']['sources']['mcp-platform']['rev']
for manifest in (cache / 'git-v0/checkouts').glob('*/*/pyproject.toml'):
    if tomllib.loads(manifest.read_text()).get('project', {}).get('name') != 'mcp-platform':
        continue
    repo = manifest.parent
    result = subprocess.run(['git', '-c', 'safe.directory=' + str(repo), '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip() == revision:
        print(repo)
        break
else:
    raise SystemExit('先执行 uv sync，或设置 HUB_RUNTIME_SOURCE 指向锁定的公共运行时源码')
PY
)
fi
uv build --wheel "$task_runtime_source" --out-dir "$task_stage/wheels"
task_events_source=${HUB_EVENTS_SOURCE:-}
if [[ -z "$task_events_source" ]]; then
  task_events_source=$("$task_repo/.venv/bin/python" - <<'PY'
import os, pwd, subprocess
from pathlib import Path
owner_home = Path(pwd.getpwuid(Path('.venv').stat().st_uid).pw_dir)
cache = Path(os.environ.get('UV_CACHE_DIR', str(owner_home / '.cache/uv')))
revision = '59f91c009207528a4183e6d6db242f6ccf4117cd'
for manifest in (cache / 'git-v0/checkouts').glob('*/*/mmp-platform/events/pyproject.toml'):
    repo = manifest.parents[2]
    result = subprocess.run(['git', '-c', 'safe.directory=' + str(repo), '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip() == revision:
        print(manifest.parent)
        break
else:
    raise SystemExit('先执行 uv sync，或设置 HUB_EVENTS_SOURCE 指向锁定版本的 mmp-platform/events')
PY
)
fi
uv build --wheel "$task_events_source" --out-dir "$task_stage/wheels"
# 私有 Git 依赖已在现有锁定基础镜像中；构建上下文只包含 wheel 和非秘密依赖。
cat > "$task_stage/Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY wheels /tmp/hub-wheels
RUN uv pip install --system 'psycopg[binary]==3.3.6' && uv pip install --system --no-deps /tmp/hub-wheels/*.whl && uv pip check --system && rm -rf /tmp/hub-wheels
CMD ["personal-data-hub"]
EOF
docker inspect "$task_base" --format '{{.Id}}'
docker build --build-arg "BASE_IMAGE=$task_base" --tag "$task_image" "$task_stage"
