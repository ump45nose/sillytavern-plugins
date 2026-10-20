#!/bin/bash
# 日报无投递回放入口；成功时保持 stdout 为空。
set -euo pipefail
export REVIEW_APP_ROOT=/vol2/1000/Docker/personal-review
exec /home/hermes/.hermes/hermes-agent/venv/bin/python3 \
  "$(dirname "$0")/personal-review-daily-dry-run.py"
