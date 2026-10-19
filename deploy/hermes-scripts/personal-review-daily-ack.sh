#!/bin/bash
# 仅在 Hermes 已确认日报投递成功后提交本次材料的 checkpoint。
set -euo pipefail

export REVIEW_APP_ROOT=/vol2/1000/Docker/personal-review
# Python 入口位于 scripts/，必须显式把应用根加入模块检索路径。
cd "${REVIEW_APP_ROOT}"
export PYTHONPATH="${REVIEW_APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
exec /home/hermes/.hermes/hermes-agent/venv/bin/python3 \
  /vol2/1000/Docker/personal-review/scripts/daily_delivery_ack.py
