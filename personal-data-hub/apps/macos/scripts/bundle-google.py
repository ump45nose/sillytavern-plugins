"""Bundles the Google Desktop OAuth client settings into the app; never a user's tokens.

Usage: bundle-google.py "/path/Nook.app"
Source: $HUB_GOOGLE_CONFIG, else the v0 config at
~/Library/Application Support/PersonalDataHub/google-desktop-config.json (read only).
"""
import json
import os
import sys
from pathlib import Path

TOKEN_FIELDS = {"refresh_token", "access_token", "id_token", "password", "token", "authorization_code", "code_verifier"}


def client_config(values):
    if not isinstance(values, dict) or "web" in values:
        raise RuntimeError("needs a Desktop OAuth client, not a web client")
    desktop = values.get("installed", values)
    if not isinstance(desktop, dict):
        raise RuntimeError("client configuration is not an object")
    if TOKEN_FIELDS & set(values) or TOKEN_FIELDS & set(desktop):
        raise RuntimeError("configuration contains user tokens; refusing to bundle")
    client_id = desktop.get("client_id")
    if not isinstance(client_id, str) or not client_id.endswith(".apps.googleusercontent.com"):
        raise RuntimeError("client_id missing or invalid")
    result = {"client_id": client_id}
    for key in ["client_secret", "expected_calendar"]:
        value = desktop.get(key, values.get(key))
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(f"{key} is invalid")
            result[key] = value
    return result


def main(app):
    source = Path(os.getenv("HUB_GOOGLE_CONFIG") or
                  Path.home() / "Library/Application Support/PersonalDataHub/google-desktop-config.json")
    if not source.is_file():
        raise RuntimeError("Google client configuration missing; set HUB_GOOGLE_CONFIG")
    values = client_config(json.loads(source.read_text()))
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    destination = resources / "google-oauth.json"
    destination.write_text(json.dumps(values, sort_keys=True))
    destination.chmod(0o644)
    print("Bundled Google OAuth client (" + ", ".join(sorted(values)) + "); user tokens excluded")


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]).resolve())
    except Exception as error:
        print("Google config: " + (str(error) if isinstance(error, RuntimeError) else "invalid JSON"), file=sys.stderr)
        raise SystemExit(1)
