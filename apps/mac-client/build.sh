#!/usr/bin/env bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")" && pwd)
task_app="$task_root/dist/Personal Data Hub.app"
cd "$task_root"
swift build -c release
task_bin=$(swift build -c release --show-bin-path)
mkdir -p "$task_app/Contents/MacOS"
cp "$task_bin/PersonalDataHub" "$task_app/Contents/MacOS/PersonalDataHub"
cp Info.plist "$task_app/Contents/Info.plist"
codesign --force --sign - --identifier com.yuwk.personal-data-hub "$task_app"
codesign --verify --strict "$task_app"
printf '%s\n' "$task_app"
