#!/usr/bin/env bash
# restart-services.sh - 定时重启有内存泄漏风险的服务
# 用法：
#   restart-services.sh                    # 重启默认列表
#   restart-services.sh add <name>         # 添加服务到列表
#   restart-services.sh remove <name>      # 从列表移除
#   restart-services.sh list               # 查看当前列表
#   restart-services.sh run                # 执行重启（同无参数）
#
# 支持两种服务类型：
#   systemd:<unit>   -> systemctl --user restart <unit>
#   docker:<name>    -> docker restart <name>
set -u

LOG_FILE="/home/hermes/.hermes/profiles/lingjun/cron/output/restart-services.log"
LIST_FILE="/home/yuwk/cron/hermes/restart-services.list"
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR

mkdir -p "$(dirname "$LOG_FILE")"

# 初始化默认列表
if [ ! -f "$LIST_FILE" ]; then
  cat > "$LIST_FILE" << 'EOF'
# restart-services.list - 每行一个服务，格式：type:name
# 类型：systemd:<unit> 或 docker:<container>
# 以 # 开头的行为注释
systemd:hermes-dashboard.service
EOF
fi

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }

get_services() {
  grep -vE '^\s*(#|$)' "$LIST_FILE" | sed 's/\r$//' | awk '{$1=$1};1'
}

cmd="${1:-run}"

case "$cmd" in
  list)
    echo "=== Restart Services List ($LIST_FILE) ==="
    cat "$LIST_FILE"
    echo "---"
    echo "Active entries:"
    get_services
    ;;

  add)
    svc="$2"
    if grep -qxF "$svc" "$LIST_FILE" 2>/dev/null; then
      echo "Already in list: $svc"
      exit 0
    fi
    echo "$svc" >> "$LIST_FILE"
    echo "Added: $svc"
    echo "Current list:"
    get_services
    ;;

  remove)
    svc="$2"
    # 用临时文件避免 sed -i
    tmp=$(mktemp)
    grep -vxF "$svc" "$LIST_FILE" > "$tmp" || true
    mv "$tmp" "$LIST_FILE"
    echo "Removed: $svc"
    echo "Current list:"
    get_services
    ;;

  run)
    log "==== restart-services start ===="

    # 记录重启前内存
    MEM_BEFORE=$(free -m | awk '/Mem:/{print $3}')
    SWAP_BEFORE=$(free -m | awk '/Swap:/{print $3}')
    log "Before: RAM used=${MEM_BEFORE}MB, Swap used=${SWAP_BEFORE}MB"

    while IFS= read -r svc; do
      [ -z "$svc" ] && continue
      type="${svc%%:*}"
      name="${svc#*:}"

      case "$type" in
        systemd)
          log "Restarting systemd unit: $name"
          if systemctl --user restart "$name" 2>>"$LOG_FILE"; then
            log "  OK: $name restarted"
          else
            log "  FAIL: $name restart failed"
          fi
          ;;
        docker)
          log "Restarting docker container: $name"
          if docker restart "$name" >>"$LOG_FILE" 2>&1; then
            log "  OK: $name restarted"
          else
            log "  FAIL: $name restart failed"
          fi
          ;;
        *)
          log "  SKIP: unknown type '$type' for '$name'"
          ;;
      esac
    done < <(get_services)

    # 等待服务稳定
    sleep 5

    # 记录重启后内存
    MEM_AFTER=$(free -m | awk '/Mem:/{print $3}')
    SWAP_AFTER=$(free -m | awk '/Swap:/{print $3}')
    log "After:  RAM used=${MEM_AFTER}MB, Swap used=${SWAP_AFTER}MB"
    log "  RAM freed=$((MEM_BEFORE - MEM_AFTER))MB, Swap freed=$((SWAP_BEFORE - SWAP_AFTER))MB"
    log "==== restart-services done ===="
    ;;

  *)
    echo "Usage: $0 [run|list|add <type:name>|remove <type:name>]"
    echo "  type: systemd or docker"
    echo "  Examples:"
    echo "    $0 add docker:homeassistant"
    echo "    $0 add systemd:hermes-gateway.service"
    echo "    $0 list"
    echo "    $0 run"
    exit 2
    ;;
esac
