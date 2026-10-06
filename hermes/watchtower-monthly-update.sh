#!/usr/bin/env bash
# watchtower-monthly-update.sh
# 每月1日 05:00，自动更新所有 watchtower.enable=false 的容器
# 动态查询标签，无需硬编码容器名
set -u
container_proxy_url=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["container_proxy_url"])' "${CRON_LOCAL_CONFIG:-/home/yuwk/cron/env/hermes.local.json}")

LOG_FILE="/home/hermes/.hermes/profiles/lingjun/cron/output/watchtower-monthly-update.log"
mkdir -p "$(dirname "$LOG_FILE")"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

log "==== watchtower monthly update start ===="

# 查询所有 watchtower.enable=false 的运行中容器
CONTAINERS=$(docker ps --filter 'label=com.centurylinklabs.watchtower.enable=false' --format '{{.Names}}' 2>/dev/null)

if [ -z "$CONTAINERS" ]; then
  log "No containers with watchtower.enable=false label found."
  log "==== done (nothing to update) ===="
  exit 0
fi

COUNT=$(echo "$CONTAINERS" | wc -l)
log "Found $COUNT containers to update:"
echo "$CONTAINERS" | sed 's/^/  - /'

# 运行一次性 watchtower 更新
log "Starting watchtower --run-once ..."
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e HTTP_PROXY=$container_proxy_url \
  -e HTTPS_PROXY=$container_proxy_url \
  containrrr/watchtower:latest --run-once --cleanup $CONTAINERS 2>&1 | while IFS= read -r line; do
    log "$line"
  done

EXIT_CODE=${PIPESTATUS[0]}
log "watchtower exited with code: $EXIT_CODE"
log "==== watchtower monthly update done ===="
