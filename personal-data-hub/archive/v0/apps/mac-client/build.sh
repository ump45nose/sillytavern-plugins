#!/usr/bin/env bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")" && pwd)
task_app="$task_root/dist/Personal Data Hub.app"
cd "$task_root"
task_swift_args=(-c release)
if [[ -n "${PDH_SWIFT_SDK:-}" ]]; then task_swift_args+=(--sdk "$PDH_SWIFT_SDK" --build-system native); fi
swift build "${task_swift_args[@]}"
task_bin=$(swift build "${task_swift_args[@]}" --show-bin-path)
mkdir -p "$task_app/Contents/MacOS" "$task_app/Contents/Resources"
cp "$task_bin/PersonalDataHub" "$task_app/Contents/MacOS/PersonalDataHub"
cp Info.plist "$task_app/Contents/Info.plist"
cp "$task_root/Resources/AppIcon.icns" "$task_app/Contents/Resources/AppIcon.icns"
swift -suppress-warnings "$task_root/signing.swift" "$task_app"
python3 "$task_root/credential-reader/install.py"
"$task_root/../crm/.venv/bin/python" "$task_root/bundle-agents.py" "$task_app"
python3 "$task_root/bundle-google.py" "$task_app"
swift -suppress-warnings "$task_root/signing.swift" "$task_app"
codesign --verify --strict "$task_app"
printf '%s\n' "$task_app"
