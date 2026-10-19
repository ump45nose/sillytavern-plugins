#!/bin/bash
# 处理已关联附件并把 30 天未解决项目转入人工清单。
set -euo pipefail

export REVIEW_APP_ROOT=/vol2/1000/Docker/personal-review
"${REVIEW_APP_ROOT}/bin/reviewctl" attachment process >/dev/null
"${REVIEW_APP_ROOT}/bin/reviewctl" attachment expire >/dev/null
