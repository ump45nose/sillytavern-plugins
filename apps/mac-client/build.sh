#!/usr/bin/env bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")" && pwd)
task_app="$task_root/dist/Personal Data Hub.app"
task_viewer_base=""
if [[ "${1:-}" == "--viewer-only" ]]; then
    task_viewer_base="${2:-/Applications/Personal Data Hub.app}"
    # Reuse the installed, signed resources and existing identity for a UI update.
    [[ -d "$task_viewer_base" ]]
    task_viewer_base=$(cd "$task_viewer_base" && pwd)
    [[ "$task_viewer_base" != "$task_app" ]]
    [[ -f "$HOME/Library/Application Support/PersonalDataHub/Signing/identity.json" ]]
    [[ -f "$HOME/Library/Application Support/PersonalDataHub/Signing/credential-reader.json" ]]
    python3 - "$task_viewer_base" <<'PY'
import json, pathlib, subprocess, sys
identity = json.loads((pathlib.Path.home() / 'Library/Application Support/PersonalDataHub/Signing/identity.json').read_text())
certificate = identity['certificateSHA1']
if len(certificate) != 40 or any(c not in '0123456789abcdefABCDEF' for c in certificate):
    raise SystemExit('Invalid existing signing identity')
requirement = 'identifier "com.yuwk.personal-data-hub" and anchor = H"' + certificate + '"'
subprocess.run(['codesign', '--verify', '--strict', '-R', '=' + requirement, sys.argv[1]], check=True)
PY
elif [[ $# != 0 ]]; then
    printf '%s\n' 'Usage: build.sh [--viewer-only EXISTING_APP]' >&2
    exit 1
fi
cd "$task_root"
task_swift_args=(-c release)
if [[ -n "${PDH_SWIFT_SDK:-}" ]]; then task_swift_args+=(--sdk "$PDH_SWIFT_SDK" --build-system native); fi
swift build "${task_swift_args[@]}"
task_bin=$(swift build "${task_swift_args[@]}" --show-bin-path)
if [[ -n "$task_viewer_base" ]]; then
    rm -rf "$task_app"
    ditto "$task_viewer_base" "$task_app"
fi
mkdir -p "$task_app/Contents/MacOS" "$task_app/Contents/Resources"
cp "$task_bin/PersonalDataHub" "$task_app/Contents/MacOS/PersonalDataHub"
cp Info.plist "$task_app/Contents/Info.plist"
cp "$task_root/Resources/AppIcon.icns" "$task_app/Contents/Resources/AppIcon.icns"
swift -suppress-warnings "$task_root/signing.swift" "$task_app"
if [[ -z "$task_viewer_base" ]]; then
    python3 "$task_root/credential-reader/install.py"
    "$task_root/../crm/.venv/bin/python" "$task_root/bundle-agents.py" "$task_app"
    python3 "$task_root/bundle-google.py" "$task_app"
    swift -suppress-warnings "$task_root/signing.swift" "$task_app"
fi
codesign --verify --strict "$task_app"
printf '%s\n' "$task_app"
