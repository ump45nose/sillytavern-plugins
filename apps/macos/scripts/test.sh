#!/usr/bin/env bash
# Command Line Tools ship the swift-testing macro plugin but SwiftPM does not put it on the plugin path.
set -euo pipefail
cd "$(dirname "$0")/.."
plugins="$(dirname "$(dirname "$(xcrun --find swift)")")/lib/swift/host/plugins/testing"
swift test -Xswiftc -plugin-path -Xswiftc "$plugins" "$@"
