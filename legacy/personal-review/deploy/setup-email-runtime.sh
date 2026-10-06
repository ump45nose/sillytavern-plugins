#!/usr/bin/env bash
# 为邮件 MCP 采集器创建与 Hermes Agent 解耦的 Python 运行环境。
set -euo pipefail

APP_ROOT="${REVIEW_APP_ROOT:-/vol2/1000/Docker/personal-review}"
VENV_ROOT="$APP_ROOT/.venv"

# 由部署用户创建环境；安装约束来自 pyproject.toml 的 email extra。
python3 -m venv "$VENV_ROOT"
"$VENV_ROOT/bin/python3" -m pip install --upgrade pip
"$VENV_ROOT/bin/python3" -m pip install "$APP_ROOT[email]"

# 运行账户只需要读取环境并执行，不获得修改应用静态代码的额外权限。
chown -R hermes:hermes "$VENV_ROOT"
find "$VENV_ROOT" -type d -exec chmod 0750 {} +
find "$VENV_ROOT" -type f -exec chmod u=rw,g=r,o= {} +
find "$VENV_ROOT/bin" -type f -exec chmod u=rwx,g=rx,o= {} +

