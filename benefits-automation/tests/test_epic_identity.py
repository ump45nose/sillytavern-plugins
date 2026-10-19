import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from platforms.epic.native import _browser_options


class IdentityTests(unittest.TestCase):
    def test_restart_reuses_the_identity_stored_with_the_account_profile(self):
        calls = []
        identity = {"navigator.userAgent": "Firefox fixture", "canvas:seed": 123}

        def launch_options(*, config, **options):
            calls.append(config)
            data = json.dumps(identity if config is None else config)
            return {**options, "env": {"CAMOU_CONFIG_2": data[15:],
                    "CAMOU_CONFIG_1": data[:15], "DISPLAY": ":0"}}

        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {
                "camoufox.utils": SimpleNamespace(launch_options=launch_options)}):
            _browser_options({}, directory)
            _browser_options({}, directory)
            path = Path(directory) / "browser-identity.json"
            self.assertEqual(json.loads(path.read_text()), identity)
            self.assertEqual(calls, [None, identity])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_saved_identity_is_reported_without_rotating_or_overwriting_it(self):
        def unexpected(**options):
            self.fail("A damaged saved identity must not generate a new browser")

        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {
                "camoufox.utils": SimpleNamespace(launch_options=unexpected)}):
            path = Path(directory) / "browser-identity.json"
            for raw in ("null", "[]", "{}", "{broken"):
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(ValueError):
                        _browser_options({}, directory)
                    self.assertEqual(path.read_text(), raw)
