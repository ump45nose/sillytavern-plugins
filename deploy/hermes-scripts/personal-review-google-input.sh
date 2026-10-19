#!/usr/bin/env bash
set -euo pipefail

# Google 原始输入由 no-agent 任务生成，凭据内容不会进入参数、stdout 或 Hermes prompt。
cd /vol2/1000/Docker/personal-review
export PYTHONPATH=.
exec /home/hermes/.hermes/hermes-agent/venv/bin/python3 scripts/work_google_daily_input.py
