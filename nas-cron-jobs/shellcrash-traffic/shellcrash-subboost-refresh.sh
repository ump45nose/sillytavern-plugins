#!/usr/bin/env bash
set -euo pipefail

crash_dir=/etc/ShellCrash
cfg_file="$crash_dir/configs/ShellCrash.cfg"
target="$crash_dir/yamls/config.yaml"
core=/tmp/ShellCrash/CrashCore
candidate=$(mktemp /tmp/shellcrash-subboost-refresh.XXXXXX)

cleanup() {
  [[ ! -e "$candidate" ]] || unlink "$candidate"
}
trap cleanup EXIT

url=$(awk -F= '/^Url=/{v=substr($0,index($0,"=")+1); gsub(/^['"'"']|['"'"']$/,"",v); print v; exit}' "$cfg_file")
[[ "$url" == http://127.0.0.1:13000/api/subscriptions/* ]]

curl --fail --silent --show-error --max-time 90 --output "$candidate" "$url"
chmod 600 "$candidate"
"$core" -t -d "$crash_dir" -f "$candidate" >/dev/null

if cmp -s "$candidate" "$target"; then
  exit 0
fi

stamp=$(date +%Y%m%d-%H%M%S)
backup="$crash_dir/backups/subboost-refresh-$stamp.yaml"
install -d -m 700 "$crash_dir/backups"
install -m 600 "$target" "$backup"
install -m 600 "$candidate" "$target"
systemctl restart shellcrash.service

