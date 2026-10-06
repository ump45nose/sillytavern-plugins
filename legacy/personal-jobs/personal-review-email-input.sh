#!/bin/bash
# 21:00 邮件输入薄入口；业务实现保留在 personal_review 应用中。
set -euo pipefail
export REVIEW_APP_ROOT=/vol2/1000/Docker/personal-review
EMAIL_PYTHON="${HERMES_AGENT_ROOT:-/home/hermes/.hermes/hermes-agent}/venv/bin/python3"

# 邮件 MCP 依赖与 Hermes Agent 解耦，缺失时明确失败而不是回退到不兼容环境。
if [[ ! -x "$EMAIL_PYTHON" ]]; then
  echo '{"status":"error","type":"RuntimeMissing","message":"Personal Review 邮件运行环境未安装"}' >&2
  exit 2
fi

exec "$EMAIL_PYTHON" \
  "$(dirname "$0")/personal-review-email-input.py"
