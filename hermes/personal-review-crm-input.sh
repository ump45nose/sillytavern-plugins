#!/usr/bin/env bash
set -euo pipefail

# CRM 定时输入只运行确定性只读 CLI；任何失败都会阻止生成“零变化”假快照。
day="$(TZ=Asia/Shanghai date +%F)"
umask 077
temporary="$(mktemp "${TMPDIR:-/tmp}/personal-review-crm.XXXXXX.json")"
trap 'rm -f "$temporary"' EXIT
docker exec personal-crm-crm-1 personal-crm daily-summary \
  --date "${day}" --timezone Asia/Shanghai > "${temporary}"
chmod 0600 "${temporary}"

# 导入器只保留计数、人物名和分类计数，不保存关系正文。
cd /vol2/1000/Docker/personal-review
./bin/reviewctl crm import --date "${day}" --content-file "${temporary}"
