"""Package Desktop OAuth application settings, never a user's login tokens."""
import json
import os
from pathlib import Path
import sys

TOKEN_FIELDS = {"refresh_token", "access_token", "id_token", "password", "token", "authorization_code", "code_verifier"}


def application_config(values):
    if not isinstance(values, dict) or "web" in values:
        raise RuntimeError("Google_packaging_requires_Desktop_application_configuration")
    desktop = values.get("installed", values)
    if not isinstance(desktop, dict):
        raise RuntimeError("Google_application_configuration_invalid")
    if TOKEN_FIELDS.intersection(values) or TOKEN_FIELDS.intersection(desktop):
        raise RuntimeError("Google_user_tokens_must_not_be_packaged")
    client_id = desktop.get("client_id")
    if not isinstance(client_id, str) or not client_id.endswith(".apps.googleusercontent.com"):
        raise RuntimeError("Google_application_client_id_missing_or_invalid")
    result = {"client_id": client_id}
    for key in ["client_secret", "expected_calendar"]:
        value = desktop.get(key, values.get(key))
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError("Google_application_configuration_invalid")
            result[key] = value
    return result


def build(app, configuration=None):
    source = Path(configuration or os.getenv("PDH_GOOGLE_CONFIG") or
                  Path.home() / "Library/Application Support/PersonalDataHub/google-desktop-config.json")
    if not source.is_file():
        raise RuntimeError("Google_application_configuration_missing_set_PDH_GOOGLE_CONFIG")
    values = application_config(json.loads(source.read_text()))
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    destination = resources / "google-oauth.json"
    destination.write_text(json.dumps(values, sort_keys=True))
    destination.chmod(0o644)


if __name__ == "__main__":
    try:
        build(Path(sys.argv[1]).resolve())
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else "Google_application_configuration_invalid")
        raise SystemExit(1)
    print("Bundled Google Desktop application configuration; user tokens excluded")
