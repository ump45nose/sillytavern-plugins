#!/usr/bin/env bash
# Builds, bundles and signs dist/Nook.app. Usage: scripts/build.sh [--install]
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
app="$root/dist/Nook.app"
cd "$root"

swift build -c release
bin=$(swift build -c release --show-bin-path)

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin/PersonalHub" "$app/Contents/MacOS/PersonalHub"
cp Info.plist "$app/Contents/Info.plist"

iconset="$root/dist/AppIcon.iconset"
rm -rf "$iconset"
"$app/Contents/MacOS/PersonalHub" --render-iconset "$iconset"
iconutil -c icns "$iconset" -o "$app/Contents/Resources/AppIcon.icns"
rm -rf "$iconset"
python3 "$root/scripts/bundle-google.py" "$app"

swift -suppress-warnings "$root/scripts/sign.swift" "$app"
printf '%s\n' "$app"

if [[ "${1:-}" == "--install" ]]; then
  "$root/scripts/install-credentials.sh"
  "$root/scripts/install.sh" "$app"
fi
