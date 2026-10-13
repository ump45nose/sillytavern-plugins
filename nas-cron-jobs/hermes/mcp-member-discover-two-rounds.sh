#!/bin/bash
# 在 Hermes lingjun profile 中串行执行两轮 MCP Member 候选发现，并保留可审计结果。
set -Eeuo pipefail

readonly APP_ROOT="/vol2/1000/Docker/mcp-member-contributor"
readonly GLOBAL_HERMES_ENV="/home/hermes/.hermes/.env"
export PATH="/usr/local/bin:/usr/bin:/bin"

readonly RUNNER="${APP_ROOT}/run.py"
readonly STATE_FILE="${APP_ROOT}/state/state.json"
readonly LOG_ROOT="${APP_ROOT}/logs"
readonly LOCK_FILE="${APP_ROOT}/discover.lock"
readonly PYTHON_BIN="/home/hermes/.hermes/hermes-agent/venv/bin/python"
readonly GH_BIN="/usr/bin/gh"
readonly JQ_BIN="/usr/bin/jq"
readonly TIMEOUT_BIN="/usr/bin/timeout"
readonly FLOCK_BIN="/usr/bin/flock"

# 输出符合 mcp-member-contributor 交付边界的失败报告，并返回非零状态。
# 参数：$1 为阻塞原因；$2 为建议的下一步。
fail_report() {
  local reason="$1"
  local next_step="$2"

  printf '候选：未完成两轮发现\n'
  printf '实际改动：无代码改动、无公开改动\n'
  printf '测试：定时脚本前置检查失败\n'
  printf '公开动作：无\n'
  printf '阻塞项：%s\n' "${reason}"
  printf '下一步：%s\n' "${next_step}"
  return 2
}

# 校验 cron 运行所需的固定命令、GitHub 凭据和登录身份。
preflight() {
  local required_path
  local github_token
  local login

  for required_path in \
    "${RUNNER}" \
    "${PYTHON_BIN}" \
    "${GH_BIN}" \
    "${JQ_BIN}" \
    "${TIMEOUT_BIN}" \
    "${FLOCK_BIN}" \
    "/usr/bin/git"; do
    if [[ ! -x "${required_path}" ]]; then
      fail_report "缺少运行依赖：${required_path}" "修复远端依赖后再恢复 cron"
      return $?
    fi
  done

  # 仅从运行环境读取凭据，不把 token 写入参数、日志或状态文件。
  github_token="${GH_TOKEN:-${MCP_GITHUB_API_KEY:-}}"
  if [[ -z "${github_token}" && -r "${GLOBAL_HERMES_ENV}" ]]; then
    # lingjun profile 可能用空变量覆盖全局值；仅在子进程内读取既有全局凭据。
    if ! github_token="$(/usr/bin/python3 -c '
import sys
from dotenv import dotenv_values
values = dotenv_values(sys.argv[1])
print(values.get("MCP_GITHUB_API_KEY") or values.get("GH_TOKEN") or values.get("GITHUB_TOKEN") or "")
' "${GLOBAL_HERMES_ENV}")"; then
      fail_report "无法读取 Hermes 全局 GitHub 凭据" "检查 ${GLOBAL_HERMES_ENV} 的权限与格式"
      return $?
    fi
  fi
  if [[ -z "${github_token}" ]]; then
    fail_report "GitHub 凭据未注入" "通过 Hermes 根共享安全配置注入凭据"
    return $?
  fi

  export GH_TOKEN="${github_token}"
  unset github_token

  if ! login="$(${TIMEOUT_BIN} --signal=TERM --kill-after=5s 30s \
      "${GH_BIN}" api user --jq .login 2>/dev/null)"; then
    fail_report "GitHub 身份校验失败" "修复凭据或网络后再恢复 cron"
    return $?
  fi

  expected_login=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["github_login"])' "${CRON_LOCAL_CONFIG:-/home/yuwk/cron/env/hermes.local.json}")
  if [[ "${login}" != "${expected_login}" ]]; then
    fail_report "GitHub 登录账号与本地预期身份不符" "切换到预期账号凭据后再恢复 cron"
    return $?
  fi
}

# 串行运行单轮 discover，验证退出码与 JSON 契约后保存原始结果。
# 参数：$1 为轮次；$2 为本次运行日志目录。
run_round() {
  local round="$1"
  local run_dir="$2"
  local output_file="${run_dir}/round-${round}.json"
  local error_file="${run_dir}/round-${round}.stderr.log"
  local exit_code

  set +e
  "${TIMEOUT_BIN}" --signal=TERM --kill-after=30s 8m \
    "${PYTHON_BIN}" "${RUNNER}" --state "${STATE_FILE}" discover --limit 3 \
    >"${output_file}" 2>"${error_file}"
  exit_code=$?
  set -e

  if [[ ${exit_code} -ne 0 ]]; then
    if [[ ${exit_code} -eq 124 ]]; then
      fail_report "第 ${round} 轮 discover 超时" "检查 GitHub 网络或限流后重试"
    else
      fail_report "第 ${round} 轮 discover 失败，退出码 ${exit_code}" "检查 ${error_file} 与本轮 JSON 后重试"
    fi
    return $?
  fi

  # 只接受 discover 的结构化结果；top_blocked 永远不进入后续候选集合。
  if ! "${JQ_BIN}" -e '
      .command == "discover"
      and (.selected | type == "array")
      and (.selected_count | type == "number")
      and (.blocked_count | type == "number")
      and (.warnings | type == "array")
    ' "${output_file}" >/dev/null; then
    fail_report "第 ${round} 轮返回了无效 JSON" "检查 ${output_file} 后重试"
    return $?
  fi
}

# 汇总两轮发现，只输出候选、阻塞计数和安全的下一步，不执行 prepare/submit。
# 参数：$1 为本次运行日志目录。
print_summary() {
  local run_dir="$1"
  local round_one="${run_dir}/round-1.json"
  local round_two="${run_dir}/round-2.json"
  local selected_one
  local selected_two
  local blocked_one
  local blocked_two
  local warnings_one
  local warnings_two
  local candidate_urls

  selected_one="$(${JQ_BIN} -r '.selected_count' "${round_one}")"
  selected_two="$(${JQ_BIN} -r '.selected_count' "${round_two}")"
  blocked_one="$(${JQ_BIN} -r '.blocked_count' "${round_one}")"
  blocked_two="$(${JQ_BIN} -r '.blocked_count' "${round_two}")"
  warnings_one="$(${JQ_BIN} -r '.warnings | length' "${round_one}")"
  warnings_two="$(${JQ_BIN} -r '.warnings | length' "${round_two}")"
  candidate_urls="$(${JQ_BIN} -rs '
    [.[].selected[]?.url] | unique | if length == 0 then "无" else join(", ") end
  ' "${round_one}" "${round_two}")"

  printf '候选：第 1 轮 %s 个，第 2 轮 %s 个；%s\n' \
    "${selected_one}" "${selected_two}" "${candidate_urls}"
  printf '实际改动：仅更新本地候选状态与运行日志；无代码改动\n'
  printf '测试：两轮 discover 均通过退出码与 JSON 契约校验\n'
  printf '公开动作：无\n'
  printf '阻塞项：第 1 轮 %s 个，第 2 轮 %s 个；warnings=%s/%s\n' \
    "${blocked_one}" "${blocked_two}" "${warnings_one}" "${warnings_two}"
  printf '下一步：只对 selected 候选按技能进入 prepare → submit；本 cron 不自动提交\n'
}

# 主流程：加全局锁、执行前置检查，再严格串行运行两轮。
main() {
  local run_dir

  mkdir -p "${APP_ROOT}/state" "${LOG_ROOT}"
  chmod 0750 "${APP_ROOT}/state" "${LOG_ROOT}"

  exec 9>"${LOCK_FILE}"
  if ! "${FLOCK_BIN}" -n 9; then
    fail_report "已有 discover 实例在运行" "等待当前实例结束，不要并发执行"
    return $?
  fi

  preflight

  run_dir="${LOG_ROOT}/$(date '+%Y%m%dT%H%M%S%z')"
  mkdir -p "${run_dir}"
  chmod 0750 "${run_dir}"

  run_round 1 "${run_dir}"
  run_round 2 "${run_dir}"
  print_summary "${run_dir}"
}

main "$@"
