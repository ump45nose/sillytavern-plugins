#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/subboost-android-build.XXXXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT
python3 "$source_dir/prepare.py" "$build_dir"
docker build --network host --progress plain \
  -t local/subboost:2.8.1-android-tailscale-v1 "$build_dir"
