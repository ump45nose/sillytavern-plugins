#!/usr/bin/env bash
# Installs to ~/Applications/Personal Hub.app, keeping the previous build alongside.
# Only touches com.yuwk.personal-hub; the v0 "Personal Data Hub" app keeps running.
set -euo pipefail
src=${1:?usage: install.sh "/path/Personal Hub.app"}
dest="$HOME/Applications/Personal Hub.app"
# Outside ~/Applications so Launch Services and login items never pick the old copy.
previous="$HOME/Library/Application Support/PersonalHub/previous/Personal Hub.app"

codesign --verify --strict "$src"
osascript -e 'tell application id "com.yuwk.personal-hub" to quit' >/dev/null 2>&1 || true
for _ in $(seq 1 20); do
  pgrep -f "Personal Hub.app/Contents/MacOS/PersonalHub" >/dev/null || break
  sleep 0.25
done

mkdir -p "$HOME/Applications"
if [[ -d "$dest" ]]; then
  rm -rf "$previous"
  mkdir -p "$(dirname "$previous")"
  mv "$dest" "$previous"
fi
ditto "$src" "$dest"
open "$dest"
printf 'Installed %s\n' "$dest"
