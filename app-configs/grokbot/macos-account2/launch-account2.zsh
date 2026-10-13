#!/bin/zsh
# Grok Bot 副号启动入口。可直接粘贴到 Automator 的“运行 Shell 脚本”。
set -eu
umask 077

BINARY="/Applications/Grok Bot.app/Contents/MacOS/Grok Bot"
PROFILE="$HOME/Library/Application Support/Grok Bot-Account2"

if [[ ! -x "$BINARY" ]]; then
  printf '找不到可执行文件：%s\n请确认 Grok Bot 已安装到 /Applications，或修改脚本中的 BINARY 路径。\n' "$BINARY" >&2
  exit 1
fi

mkdir -p "$PROFILE/sand-data"

# 后台运行并断开标准输入/输出，让 Automator 启动后可以退出。
# 已打开副号时请切换到已有窗口；此脚本不负责查重或激活窗口。
/usr/bin/nohup /usr/bin/env SAND_DATA_ROOT="$PROFILE/sand-data" \
  "$BINARY" --user-data-dir="$PROFILE" </dev/null >/dev/null 2>&1 &
