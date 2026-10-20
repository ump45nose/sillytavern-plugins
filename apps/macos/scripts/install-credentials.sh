#!/usr/bin/env bash
# Installs the fixed credential helper once. Later runs only verify it byte for byte:
# the login keychain trusts that exact binary, so it is never rebuilt or re-signed.
set -euo pipefail
umask 077
root=$(cd "$(dirname "$0")/.." && pwd)
private="$HOME/Library/Application Support/PersonalHub"
app="$private/Personal Hub Credentials.app"
binary_name=PersonalHubCredentials
manifest="$private/credential-helper.json"
bundle_id=com.yuwk.personal-hub.credentials
identity=$(/usr/bin/plutil -extract certificateSHA1 raw -o - \
  "$HOME/Library/Application Support/PersonalDataHub/Signing/identity.json")
requirement="identifier \"$bundle_id\" and anchor = H\"$identity\""
source_sha=$(shasum -a 256 "$root/credential-helper/main.swift" | cut -d' ' -f1)

expected() {
  printf '{"binarySHA256":"%s","certificateSHA1":"%s","sourceSHA256":"%s"}' "$1" "$identity" "$source_sha"
}

if [[ -e "$app" || -e "$manifest" ]]; then
  if [[ ! -e "$app" || ! -e "$manifest" ]]; then
    echo "Credential helper or its manifest is missing; restore both, automatic replacement is disabled" >&2
    exit 1
  fi
  actual=$(shasum -a 256 "$app/Contents/MacOS/$binary_name" | cut -d' ' -f1)
  if [[ "$(cat "$manifest")" != "$(expected "$actual")" ]]; then
    echo "Credential helper changed; keep the approved binary and migrate explicitly" >&2
    exit 1
  fi
  codesign --verify --strict -R="$requirement" "$app"
  echo "Credential helper preserved byte for byte"
  exit 0
fi

mkdir -p "$private"
work=$(mktemp -d "$private/credential-helper.XXXXXX")
trap 'rm -rf "$work"' EXIT
candidate="$work/Personal Hub Credentials.app"
mkdir -p "$candidate/Contents/MacOS"
swiftc -O -suppress-warnings -target "$(uname -m)-apple-macosx14.0" \
  "$root/credential-helper/main.swift" -o "$candidate/Contents/MacOS/$binary_name"
/usr/bin/plutil -create xml1 "$candidate/Contents/Info.plist"
for kv in "CFBundleIdentifier=$bundle_id" "CFBundleExecutable=$binary_name" \
  "CFBundleName=Personal Hub Credentials" "CFBundleVersion=1" "CFBundlePackageType=APPL" \
  "LSMinimumSystemVersion=14.0"; do
  /usr/bin/plutil -insert "${kv%%=*}" -string "${kv#*=}" "$candidate/Contents/Info.plist"
done
/usr/bin/plutil -insert LSUIElement -bool YES "$candidate/Contents/Info.plist"
swift -suppress-warnings "$root/scripts/sign.swift" "$candidate"
codesign --verify --strict -R="$requirement" "$candidate"
digest=$(shasum -a 256 "$candidate/Contents/MacOS/$binary_name" | cut -d' ' -f1)
ditto "$candidate" "$app"
expected "$digest" >"$manifest"
chmod 600 "$manifest"
echo "Credential helper installed; login keychain unchanged until the first Google sign-in"
