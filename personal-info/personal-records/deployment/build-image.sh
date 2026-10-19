#!/usr/bin/env bash
set -euo pipefail
task_repo=$(cd "$(dirname "$0")/.." && pwd)
task_stage=$(mktemp -d)
trap 'rm -rf "$task_stage"' EXIT
cd "$task_repo"
uv export --no-header --frozen --extra server --no-dev --no-emit-project --no-emit-package mcp-platform --output-file "$task_stage/requirements.txt" >/dev/null
uv build --wheel --out-dir "$task_stage/wheels"
# Obtain exactly the platform source installed from the locked Git revision.
task_runtime=$("$task_repo/.venv/bin/python" - <<'PY'
import os, pwd, subprocess, tomllib
from pathlib import Path
owner = Path(pwd.getpwuid(Path('.venv').stat().st_uid).pw_dir)
cache = Path(os.environ.get('UV_CACHE_DIR', str(owner / '.cache/uv')))
revision = tomllib.loads(Path('pyproject.toml').read_text())['tool']['uv']['sources']['mcp-platform']['rev']
for manifest in (cache / 'git-v0/checkouts').glob('*/*/pyproject.toml'):
    if tomllib.loads(manifest.read_text()).get('project', {}).get('name') != 'mcp-platform': continue
    repo = manifest.parent
    result = subprocess.run(['git', '-c', 'safe.directory='+str(repo), '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip() == revision:
        print(repo); break
else: raise SystemExit('Run uv sync --extra server first')
PY
)
uv build --wheel "$task_runtime" --out-dir "$task_stage/wheels"
cat > "$task_stage/Dockerfile" <<'DOCKER'
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY wheels /tmp/wheels
RUN pip install --no-cache-dir --no-deps /tmp/wheels/*.whl && pip check && rm -rf /tmp/wheels /tmp/requirements.txt
USER 1000:1001
CMD ["personal-records", "serve"]
DOCKER
"$task_repo/.venv/bin/python" - "$task_stage" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
files = [root/'requirements.txt', *sorted((root/'wheels').glob('*.whl'))]
print(json.dumps({'artifacts': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}))
PY
docker build --tag "${RECORDS_IMAGE:-local/personal-records:0.1.0}" "$task_stage"
