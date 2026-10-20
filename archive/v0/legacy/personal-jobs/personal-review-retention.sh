#!/bin/bash
# 按版本化策略归档过期 Skysight raw，并在年度总结后归档 derived。
set -euo pipefail

export REVIEW_APP_ROOT=/vol2/1000/Docker/personal-review
"${REVIEW_APP_ROOT}/bin/reviewctl" retention apply >/dev/null
