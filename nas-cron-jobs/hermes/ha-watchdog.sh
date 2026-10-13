#!/usr/bin/env bash
# ha-watchdog.sh - 轻量 Home Assistant 存活探测 + 卡死现场抓取
# Hermes no-agent cron 使用：
#   健康 / 冷却中：stdout 空（scheduler 静默）
#   首次判定异常：写本地 dump，stdout 输出摘要（由 deliver 推送）
set -u

CONTAINER="${HA_CONTAINER:-homeassistant}"
LOCAL_URL=$(/home/hermes/.hermes/hermes-agent/venv/bin/python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ.get('HERMES_CRON_CONFIG', '/home/yuwk/cron/env/hermes.local.json'))
print(json.loads(p.read_text()).get('ha_url', '') if p.exists() else '')
PY
) || exit 1
URL="${HA_URL:-${LOCAL_URL:-http://127.0.0.1:8123/}}"
CURL_TIMEOUT="${HA_CURL_TIMEOUT:-4}"
# 连续失败次数达到阈值才判定异常，避免重启瞬间误报
FAIL_THRESHOLD="${HA_FAIL_THRESHOLD:-2}"
# 同一故障窗口内告警冷却（秒）
ALERT_COOLDOWN="${HA_ALERT_COOLDOWN:-3600}"
# RSS 过低 + CPU 过高 也视作假活（MB / %）
LOW_RSS_MB="${HA_LOW_RSS_MB:-80}"
HIGH_CPU="${HA_HIGH_CPU:-80}"

BASE_DIR="/home/hermes/.hermes/profiles/lingjun/cron/output/ha-watchdog"
STATE_FILE="$BASE_DIR/state.env"
LOG_FILE="$BASE_DIR/watchdog.log"
DUMP_DIR="$BASE_DIR/dumps"

mkdir -p "$DUMP_DIR"
touch "$STATE_FILE"

ts() { date '+%Y-%m-%d %H:%M:%S %z'; }
log() { echo "[$(ts)] $*" >> "$LOG_FILE"; }

load_state() {
  FAIL_COUNT=0
  LAST_ALERT_EPOCH=0
  LAST_STATUS=ok
  # shellcheck disable=SC1090
  [ -f "$STATE_FILE" ] && . "$STATE_FILE" || true
  FAIL_COUNT=${FAIL_COUNT:-0}
  LAST_ALERT_EPOCH=${LAST_ALERT_EPOCH:-0}
  LAST_STATUS=${LAST_STATUS:-ok}
}

save_state() {
  cat > "$STATE_FILE" <<STATE
FAIL_COUNT=$FAIL_COUNT
LAST_ALERT_EPOCH=$LAST_ALERT_EPOCH
LAST_STATUS=$LAST_STATUS
LAST_CHECK_EPOCH=$(date +%s)
LAST_HTTP=${HTTP_CODE:-}
LAST_HA_PID=${HA_PID:-}
LAST_HA_CPU=${HA_CPU:-}
LAST_HA_RSS_MB=${HA_RSS_MB:-}
STATE
}

get_ha_pid() {
  # 优先容器内 python HA 进程
  local pid
  pid=$(docker top "$CONTAINER" -eo pid,cmd 2>/dev/null | awk '/python3 -m homeassistant/{print $1; exit}')
  if [ -z "${pid:-}" ]; then
    pid=$(pgrep -f 'python3 -m homeassistant --config' 2>/dev/null | head -1 || true)
  fi
  echo "${pid:-}"
}

probe() {
  HTTP_CODE=$(curl --noproxy '*' -sS -m "$CURL_TIMEOUT" -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || true)
  HTTP_CODE=$(printf '%s' "$HTTP_CODE" | tr -cd '0-9')
  case "$HTTP_CODE" in
    200|201|301|302|401|403) ;;
    *)
      # curl 失败时可能空串或异常拼接，统一成 000
      if [ ${#HTTP_CODE} -ne 3 ]; then HTTP_CODE=000; fi
      ;;
  esac

  HA_PID=$(get_ha_pid)
  HA_CPU=0
  HA_RSS_MB=0
  HA_STAT=?
  if [ -n "$HA_PID" ] && [ -r "/proc/$HA_PID/stat" ]; then
    # (comm) 可能含空格，用 ps 更稳
    read -r HA_CPU HA_RSS_KB HA_STAT < <(ps -p "$HA_PID" -o pcpu=,rss=,stat= 2>/dev/null | awk '{printf "%s %s %s", $1, $2, $3}')
    HA_CPU=${HA_CPU:-0}
    HA_RSS_MB=$(( ${HA_RSS_KB:-0} / 1024 ))
    HA_STAT=${HA_STAT:-?}
  fi

  CONTAINER_STATUS=$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo missing)
  STARTED_AT=$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null || echo unknown)

  HTTP_OK=0
  case "$HTTP_CODE" in
    200|201|301|302|401|403) HTTP_OK=1 ;;
  esac

  # 假活启发式：进程在、CPU 很高、RSS 异常低
  ZOMBIE_LIKE=0
  if [ -n "$HA_PID" ]; then
    cpu_int=${HA_CPU%.*}
    cpu_int=${cpu_int:-0}
    if [ "$cpu_int" -ge "$HIGH_CPU" ] && [ "$HA_RSS_MB" -gt 0 ] && [ "$HA_RSS_MB" -lt "$LOW_RSS_MB" ]; then
      ZOMBIE_LIKE=1
    fi
  fi

  if [ "$CONTAINER_STATUS" != "running" ] || [ "$HTTP_OK" -eq 0 ] || [ "$ZOMBIE_LIKE" -eq 1 ]; then
    return 1
  fi
  return 0
}

capture_dump() {
  local stamp tag dump
  stamp=$(date '+%Y%m%d_%H%M%S')
  tag="ha_unhealthy_${stamp}"
  dump="$DUMP_DIR/$tag"
  mkdir -p "$dump"

  {
    echo "=== meta ==="
    echo "time: $(ts)"
    echo "url: $URL"
    echo "http_code: $HTTP_CODE"
    echo "container: $CONTAINER status=$CONTAINER_STATUS started=$STARTED_AT"
    echo "ha_pid: ${HA_PID:-none} cpu=${HA_CPU}% rss_mb=${HA_RSS_MB} stat=${HA_STAT}"
    echo "fail_count: $FAIL_COUNT threshold=$FAIL_THRESHOLD zombie_like=$ZOMBIE_LIKE"
    echo
    echo "=== uptime/free ==="
    uptime || true
    free -h || true
    echo
    echo "=== docker inspect (brief) ==="
    docker inspect "$CONTAINER" --format 'Status={{.State.Status}} Running={{.State.Running}} OOM={{.State.OOMKilled}} Exit={{.State.ExitCode}} Error={{.State.Error}} RestartCount={{.RestartCount}} StartedAt={{.State.StartedAt}} FinishedAt={{.State.FinishedAt}} Pid={{.State.Pid}} NetworkMode={{.HostConfig.NetworkMode}}' 2>&1 || true
    echo
    echo "=== docker stats ==="
    docker stats "$CONTAINER" --no-stream 2>&1 || true
    echo
    echo "=== docker top ==="
    docker top "$CONTAINER" -eo pid,ppid,pcpu,pmem,rss,stat,etime,cmd 2>&1 || true
    echo
    echo "=== host process ==="
    if [ -n "${HA_PID:-}" ]; then
      ps -p "$HA_PID" -o pid,ppid,stat,pcpu,pmem,rss,vsz,etime,cmd 2>&1 || true
      echo "--- status ---"
      grep -E 'Name|State|Pid|PPid|Threads|VmRSS|VmSize|VmSwap|voluntary|nonvoluntary' "/proc/$HA_PID/status" 2>&1 || true
      echo "--- wchan/threads ---"
      for t in "/proc/$HA_PID/task"/*; do
        tid=$(basename "$t")
        st=$(awk '/^State:/{print $2,$3}' "$t/status" 2>/dev/null)
        wc=$(cat "$t/wchan" 2>/dev/null || echo ?)
        echo "tid=$tid state=$st wchan=$wc"
      done 2>/dev/null | head -80
    else
      echo "HA pid not found"
    fi
    echo
    echo "=== ss :8123 ==="
    ss -ltnp 2>/dev/null | grep 8123 || true
    echo "--- connections sample ---"
    ss -ntp 2>/dev/null | grep ':8123' | head -40 || true
    echo "close_wait_count=$(ss -ntp 2>/dev/null | grep ':8123' | grep -c CLOSE-WAIT || true)"
    echo
    echo "=== recent docker logs (last 150) ==="
    docker logs --tail 150 "$CONTAINER" 2>&1 || true
    echo
    echo "=== home-assistant.log tail ==="
    if [ -f /vol2/1000/Docker/homeassistant/config/home-assistant.log ]; then
      tail -n 120 /vol2/1000/Docker/homeassistant/config/home-assistant.log 2>&1 || true
    fi
    echo
    echo "=== db files ==="
    ls -lh /vol2/1000/Docker/homeassistant/config/home-assistant_v2.db* 2>&1 || true
    echo
    echo "=== top cpu/mem ==="
    ps aux --sort=-%cpu | head -12
    echo
    ps aux --sort=-%mem | head -12
  } > "$dump/snapshot.txt" 2>&1

  # 单独保留最近日志，方便直接看
  docker logs --tail 300 "$CONTAINER" > "$dump/docker.log" 2>&1 || true

  # 清理旧 dump，只留最近 20 份
  ls -1dt "$DUMP_DIR"/ha_unhealthy_* 2>/dev/null | tail -n +21 | xargs -r rm -rf

  echo "$dump"
}

# ---- main ----
load_state
now_epoch=$(date +%s)

if probe; then
  if [ "$LAST_STATUS" != "ok" ]; then
    log "RECOVERED http=$HTTP_CODE pid=${HA_PID:-none} cpu=${HA_CPU}% rss=${HA_RSS_MB}MB"
    FAIL_COUNT=0
    LAST_STATUS=ok
    save_state
    echo "- Home Assistant：已恢复"
    exit 0
  fi
  FAIL_COUNT=0
  LAST_STATUS=ok
  save_state
  log "ok http=$HTTP_CODE pid=${HA_PID:-none} cpu=${HA_CPU}% rss=${HA_RSS_MB}MB"
  # 健康：静默
  exit 0
fi

# unhealthy probe
FAIL_COUNT=$((FAIL_COUNT + 1))
LAST_STATUS=unhealthy
log "PROBE_FAIL#$FAIL_COUNT http=$HTTP_CODE container=$CONTAINER_STATUS pid=${HA_PID:-none} cpu=${HA_CPU}% rss=${HA_RSS_MB}MB zombie_like=$ZOMBIE_LIKE"

if [ "$FAIL_COUNT" -lt "$FAIL_THRESHOLD" ]; then
  save_state
  # 未达阈值，不告警不 dump（避免重启窗口噪声）；仍记日志
  exit 0
fi

# 冷却：窗口内只告警一次，但仍可在冷却外补充 dump
should_alert=1
if [ "$LAST_ALERT_EPOCH" -gt 0 ]; then
  delta=$((now_epoch - LAST_ALERT_EPOCH))
  if [ "$delta" -lt "$ALERT_COOLDOWN" ]; then
    should_alert=0
  fi
fi

dump_path=$(capture_dump)
log "DUMP $dump_path alert=$should_alert"

if [ "$should_alert" -eq 1 ]; then
  LAST_ALERT_EPOCH=$now_epoch
  save_state
  if [ "$CONTAINER_STATUS" != "running" ]; then
    echo "- Home Assistant：容器未运行（$CONTAINER_STATUS）"
  elif [ "$ZOMBIE_LIKE" -eq 1 ]; then
    echo "- Home Assistant：进程无响应（HTTP $HTTP_CODE）"
  else
    echo "- Home Assistant：访问失败（HTTP $HTTP_CODE）"
  fi
  exit 0
fi

save_state
# 冷却中：静默，只保留 dump/log
exit 0
