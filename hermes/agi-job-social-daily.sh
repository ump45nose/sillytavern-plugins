#!/usr/bin/env bash
set -euo pipefail

project_dir="${JOBFLOW_ROOT:-/home/yuwk/code/agi-job-automation}"

exec "${project_dir}/.venv/bin/python" "${project_dir}/scripts/run_rss_feeds.py" \
  --db "${project_dir}/data/jobflow.db" \
  --config "${project_dir}/config/rss-feeds.json" \
  --daily-report \
  --no-outbox
