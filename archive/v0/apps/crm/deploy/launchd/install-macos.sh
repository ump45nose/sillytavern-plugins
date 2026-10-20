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
binary_path="${CHATLOG_EXECUTABLE:-${support_dir}/bin/chatlog-keeper-v0.3.7-preview}"
client_id_path="${support_dir}/client-id"
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
binary_sha256="$(shasum -a 256 "${binary_path}" | awk '{print $1}')"

cp "${project_root}/deploy/launchd/${label}.plist.example" "${plist_path}"
PLIST_PATH="${plist_path}" \
PROGRAM_PATH="${project_root}/.venv/bin/personal-crm-wechat" \
PROJECT_ROOT="${project_root}" \
ENV_PATH="${env_path}" \
BINARY_PATH="${binary_path}" \
BINARY_SHA256="${binary_sha256}" \
SCOPES_PATH="${scopes_path}" \
CHECKPOINT_PATH="${checkpoint_path}" \
CLIENT_ID_PATH="${client_id_path}" \
LOG_PATH="${logs_dir}/wechat.log" \
ERROR_LOG_PATH="${logs_dir}/wechat.error.log" \
"${project_root}/.venv/bin/python" <<'PY'
"""把本机绝对路径写入 launchd plist，并显式覆盖迁移前机器的路径配置。"""

import os
import plistlib
import re
import uuid
from pathlib import Path
from dotenv import dotenv_values

# 设备 ID 不随重装变化；首次安装生成，明确配置的 ID 优先。
client_id_path = Path(os.environ["CLIENT_ID_PATH"])
env_values = dotenv_values(os.environ["ENV_PATH"])
client_id = os.environ.get("CRM_CLIENT_ID") or env_values.get("CRM_CLIENT_ID")
if not client_id:
    client_id = client_id_path.read_text().strip() if client_id_path.exists() else str(uuid.uuid4())
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", client_id):
    raise ValueError("CRM_CLIENT_ID 必须是最多 80 字符的设备标签")
client_id_path.write_text(client_id + "\n")
client_id_path.chmod(0o600)

plist_path = Path(os.environ["PLIST_PATH"])
with plist_path.open("rb") as stream:
    value = plistlib.load(stream)

value["ProgramArguments"] = [os.environ["PROGRAM_PATH"], "--watch"]
value["WorkingDirectory"] = os.environ["PROJECT_ROOT"]
value["EnvironmentVariables"] = {
    "CRM_ENV_FILE": os.environ["ENV_PATH"],
    "CRM_CLIENT_ID": client_id,
    # dotenv 不覆盖进程环境，以下三项负责接管旧 Mac 配置中的绝对路径。
    "CHATLOG_EXECUTABLE": os.environ["BINARY_PATH"],
    "CHATLOG_EXPECTED_SHA256": os.environ["BINARY_SHA256"],
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
