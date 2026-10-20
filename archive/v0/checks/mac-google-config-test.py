"""Ensure app packaging cannot copy user tokens or web server credentials."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("google_bundle", Path(__file__).resolve().parents[1] / "apps/mac-client/bundle-google.py")
bundler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundler)


class GoogleBundleTests(unittest.TestCase):
    def test_google_download_contains_only_desktop_application_fields(self):
        source = {"installed": {"client_id": "test.apps.googleusercontent.com", "client_secret": "native-application-setting",
                               "project_id": "project", "redirect_uris": ["http://localhost"]}}
        result = bundler.application_config(source)
        self.assertEqual(set(result), {"client_id", "client_secret"})

    def test_user_tokens_rejected_in_flat_and_downloaded_configuration(self):
        for key in bundler.TOKEN_FIELDS:
            for nested in [False, True]:
                with self.subTest(key=key, nested=nested):
                    values = {"client_id": "test.apps.googleusercontent.com", key: "private-user-token"}
                    with self.assertRaisesRegex(RuntimeError, "tokens_must_not_be_packaged"):
                        bundler.application_config({"installed": values} if nested else values)

    def test_web_credentials_and_missing_application_id_rejected(self):
        for values in [{"web": {"client_id": "test.apps.googleusercontent.com", "client_secret": "server-secret"}}, {}, {"client_id": ""}]:
            with self.assertRaises(RuntimeError):
                bundler.application_config(values)

    def test_signed_resource_uses_whitelist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "private-config.json"
            source.write_text(json.dumps({"client_id": "test.apps.googleusercontent.com", "expected_calendar": "test@example.invalid", "irrelevant": "not-for-bundle"}))
            app = root / "Hub.app"
            bundler.build(app, source)
            value = json.loads((app / "Contents/Resources/google-oauth.json").read_text())
            self.assertEqual(set(value), {"client_id", "expected_calendar"})

    def test_invalid_input_never_creates_resource(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "private-config.json"
            source.write_text(json.dumps({"client_id": "test.apps.googleusercontent.com", "refresh_token": "private-user-token"}))
            app = root / "Hub.app"
            with self.assertRaises(RuntimeError):
                bundler.build(app, source)
            self.assertFalse((app / "Contents/Resources/google-oauth.json").exists())


if __name__ == "__main__":
    unittest.main()
