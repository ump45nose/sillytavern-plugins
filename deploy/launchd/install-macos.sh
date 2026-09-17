#!/bin/zsh
set -euo pipefail

# 将当前仓库安装为用户级 LaunchAgent；秘密配置和运行时数据始终留在用户目录。
project_root="${0:A:h:h:h}"
user_home="${HOME}"
user_uid="$(id -u)"
label="com.personal-crm.wechat"
support_dir="${user_home}/Library/Application Support/personal-crm"
logs_dir="${support_dir}/logs"
agent_dir="${user_home}/Library/LaunchAgents"
env_path="${project_root}/connector.env"
binary_path="${support_dir}/bin/chatlog-keeper-v0.3.6-preview"
scopes_path="${support_dir}/wechat/whitelist-scopes.json"
checkpoint_path="${support_dir}/checkpoint.json"
plist_path="${agent_dir}/${label}.plist"

for required in \
  "${project_root}/.venv/bin/personal-crm-wechat" \
  "${env_path}" \
  "${binary_path}" \
  "${scopes_path}"; do
  if [[ ! -e "${required}" ]]; then
    print -u2 "缺少 Connector 依赖：${required}"
    exit 1
  fi
done

mkdir -p "${logs_dir}" "${agent_dir}"
chmod 600 "${env_path}" "${scopes_path}"
chmod 700 "${binary_path}"
[[ -e "${checkpoint_path}" ]] && chmod 600 "${checkpoint_path}"

cp "${project_root}/deploy/launchd/${label}.plist.example" "${plist_path}"
PLIST_PATH="${plist_path}" \
PROGRAM_PATH="${project_root}/.venv/bin/personal-crm-wechat" \
PROJECT_ROOT="${project_root}" \
ENV_PATH="${env_path}" \
BINARY_PATH="${binary_path}" \
SCOPES_PATH="${scopes_path}" \
CHECKPOINT_PATH="${checkpoint_path}" \
LOG_PATH="${logs_dir}/wechat.log" \
ERROR_LOG_PATH="${logs_dir}/wechat.error.log" \
/usr/bin/python3 <<'PY'
"""把本机绝对路径写入 launchd plist，并显式覆盖迁移前机器的路径配置。"""

import os
import plistlib
from pathlib import Path

plist_path = Path(os.environ["PLIST_PATH"])
with plist_path.open("rb") as stream:
    value = plistlib.load(stream)

value["ProgramArguments"] = [os.environ["PROGRAM_PATH"], "--watch"]
value["WorkingDirectory"] = os.environ["PROJECT_ROOT"]
value["EnvironmentVariables"] = {
    "CRM_ENV_FILE": os.environ["ENV_PATH"],
    # dotenv 不覆盖进程环境，以下三项负责接管旧 Mac 配置中的绝对路径。
    "CHATLOG_EXECUTABLE": os.environ["BINARY_PATH"],
    "CHATLOG_SCOPES": os.environ["SCOPES_PATH"],
    "CRM_CHECKPOINT": os.environ["CHECKPOINT_PATH"],
}
value["StandardOutPath"] = os.environ["LOG_PATH"]
value["StandardErrorPath"] = os.environ["ERROR_LOG_PATH"]
value["ThrottleInterval"] = 10

with plist_path.open("wb") as stream:
    plistlib.dump(value, stream, sort_keys=False)
PY
plutil -lint "${plist_path}"

# 重装服务时只替换注册信息，不删除 checkpoint 或日志。
launchctl bootout "gui/${user_uid}/${label}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${user_uid}" "${plist_path}"
launchctl kickstart -k "gui/${user_uid}/${label}"
print "已安装 ${label}。"
