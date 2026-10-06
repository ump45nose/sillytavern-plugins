#!/usr/bin/env bash
set -euo pipefail

project_dir="${JOBFLOW_ROOT:-/home/yuwk/code/agi-job-automation}"
profile_env="${HERMES_ROOT:-/home/hermes/.hermes}/.env"
lock_file=/run/user/$(id -u)/agi-job-ats-sync.lock
tmp_dir="${project_dir}/data/tmp"

provider_key=$(/usr/bin/python3 -c '
import sys
for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if line.startswith("HERMES_PROVIDER_CPA_API_KEY="):
        print(line.split("=", 1)[1].strip().strip("\"\047"))
        break
' "$profile_env")
if [[ -z "$provider_key" ]]; then
  echo "ATS 同步失败：根共享配置未配置 HERMES_PROVIDER_CPA_API_KEY"
  exit 1
fi

export JOBFLOW_LLM_BASE_URL=http://127.0.0.1:4010/cpa/v1
export JOBFLOW_LLM_MODEL="${CRON_ATS_MODEL:-grok-4.7}"
export JOBFLOW_LLM_API_KEY="$provider_key"
export PYTHONPATH="${project_dir}/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$tmp_dir"
chmod 2770 "$tmp_dir"
export TMPDIR="$tmp_dir"

exec 9>"$lock_file"
if ! flock -n 9; then
  echo "ATS 同步跳过：上一批次仍在执行"
  exit 0
fi

exec "${project_dir}/.venv/bin/python" "${project_dir}/.venv/bin/ats-sync" \
  --db "${project_dir}/data/jobflow.db" \
  --registry "${project_dir}/config/ats-sources.json" \
  --profile "${project_dir}/config/profile.local.json" \
  --mode auto \
  --trigger cron \
  --analysis-limit 200 \
  --no-outbox \
  --telegram-text
