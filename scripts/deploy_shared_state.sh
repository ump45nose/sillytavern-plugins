#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$SOURCE_DIR/mcp/shared_state_mcp.py"
TARGET="/home/hermes/.hermes/mcp-servers/shared_state_mcp.py"
PYTHON="/home/hermes/.hermes/hermes-agent/venv/bin/python"
HERMES_TMP="/home/hermes/.hermes/tmp"

sudo install -d -m 0750 -o hermes -g hermes "$HERMES_TMP"
sudo -n -u hermes env TMPDIR="$HERMES_TMP" PYTHONDONTWRITEBYTECODE=1 \
  "$PYTHON" -c 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")' \
  "$SOURCE"

sudo install -d -m 0750 -o hermes -g hermes "$(dirname "$TARGET")"
sudo install -m 0750 -o hermes -g hermes "$SOURCE" "$TARGET"

source_hash="$(sha256sum "$SOURCE" | awk '{print $1}')"
target_hash="$(sudo sha256sum "$TARGET" | awk '{print $1}')"
if [[ "$source_hash" != "$target_hash" ]]; then
  echo "shared-state deploy checksum mismatch" >&2
  exit 1
fi

echo "shared-state deployed: $target_hash"
