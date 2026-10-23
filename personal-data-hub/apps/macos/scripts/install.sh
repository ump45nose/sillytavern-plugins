#!/usr/bin/env bash
# Installs to ~/Applications/Nook.app, keeping the previous build alongside.
# Only touches com.yuwk.personal-hub; the v0 "Personal Data Hub" app keeps running.
set -euo pipefail
src=${1:?usage: install.sh "/path/Nook.app"}
dest="$HOME/Applications/Nook.app"
legacy="$HOME/Applications/Personal Hub.app"
# Outside ~/Applications so Launch Services and login items never pick the old copy.
previous="$HOME/Library/Application Support/PersonalHub/previous"

codesign --verify --strict "$src"
osascript -e 'tell application id "com.yuwk.personal-hub" to quit' >/dev/null 2>&1 || true
for _ in $(seq 1 20); do
  pgrep -f '(Nook|Personal Hub)\.app/Contents/MacOS/PersonalHub' >/dev/null || break
  sleep 0.25
done

mkdir -p "$HOME/Applications"
for installed in "$dest" "$legacy"; do
  if [[ -d "$installed" ]]; then
    backup="$previous/$(basename "$installed")"
    rm -rf "$backup"
    mkdir -p "$previous"
    mv "$installed" "$backup"
  fi
done
ditto "$src" "$dest"
open "$dest"
printf 'Installed %s\n' "$dest"
