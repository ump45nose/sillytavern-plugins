#!/usr/bin/env bash
# Applies the shipped patch to an isolated copy of the pinned upstream checkout.
# No network, Bilibili credentials, Docker daemon, or media service is used.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PIN=791dd57f2321d9093c39f38bee8528f249b06e04
if [[ $# -lt 1 || $# -gt 2 || ( $# -eq 2 && "$2" != --cargo ) ]]; then
    echo "Usage: $0 /path/to/bili-sync-upstream [--cargo]" >&2
    exit 2
fi
UPSTREAM=$(cd -- "$1" && pwd)
git -C "$UPSTREAM" cat-file -e "$PIN^{commit}"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/bili-flat-test.XXXXXXXX")
trap 'rm -rf -- "$WORK"' EXIT
git -C "$UPSTREAM" archive "$PIN" | tar -x -C "$WORK"
cd "$WORK"
git apply --check "$ROOT/bili-sync-v2.11.1-flat.patch"
git apply "$ROOT/bili-sync-v2.11.1-flat.patch"
rustc --edition 2024 --test crates/bili_sync/src/utils/flat_output.rs -o "$WORK/flat-output-tests"
"$WORK/flat-output-tests"
if [[ ${2:-} == --cargo ]]; then
    # Dependencies must already be cached. This never downloads crates or calls Bilibili.
    cargo check --offline --locked -p bili_sync
    cargo test --offline --locked -p bili_sync flat_
fi
