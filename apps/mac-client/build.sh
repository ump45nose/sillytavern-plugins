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
swift -suppress-warnings "$task_root/signing.swift" "$task_app"
codesign --verify --strict "$task_app"
python3 "$task_root/credential-reader/install.py"
printf '%s\n' "$task_app"
