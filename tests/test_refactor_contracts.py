"""Small contracts around shared boundaries; all inputs are local fixtures."""
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from favsync.common import SyncError
from favsync.gallery import read_events
from favsync.publication import accepted_size, publish_file
from favsync.adapters_pixiv_wallabag import WallabagAdapter


class RefactorContracts(unittest.TestCase):
    def test_gallery_reader_preserves_warning_policy_and_rejects_terminal_mix(self):
        expected = [[2, {"id": 1}]]
        def runner(args, timeout, output, *, warnings_are_errors):
            self.assertFalse(warnings_are_errors)
            self.assertEqual(args[-2:], ["-j", "fixture"])
            self.assertEqual(timeout, 12)
            output.write(json.dumps(expected).encode())
        self.assertEqual(read_events("config", "fixture", 12, runner=runner), expected)
        expected.append([-1, {"error": "AuthorizationError"}])
        with self.assertRaisesRegex(SyncError, "auth_required"):
            read_events("config", "fixture", 12, runner=runner)

    def test_publication_uses_same_acceptance_and_never_replaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            source.write_bytes(b"")
            for path in (source, target):
                with self.assertRaisesRegex(SyncError, "download_missing_file"):
                    accepted_size(path)
            source.write_bytes(b"complete")
            self.assertEqual(publish_file(source, target), 8)
            self.assertFalse(source.exists())
            self.assertEqual(accepted_size(target), 8)
            source.write_bytes(b"other")
            with self.assertRaisesRegex(SyncError, "destination_exists"):
                publish_file(source, target)
            self.assertEqual(target.read_bytes(), b"complete")
            self.assertEqual(source.read_bytes(), b"other")

    def test_backend_extras_keep_pins_and_full_image_install_contract(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
        self.assertFalse(any("gallery-dl" in dep or "xiaohongshu" in dep for dep in project["dependencies"]))
        extras = project["optional-dependencies"]
        self.assertEqual(set(extras["all"]), set(extras["gallery"] + extras["xhs"]))
        self.assertIn('"optional-dependencies"]["all"]', (root / "Dockerfile").read_text())

    def test_wallabag_session_reused_and_explicitly_closed(self):
        session = Mock()
        with patch("favsync.adapters_pixiv_wallabag.requests.Session", return_value=session), \
                patch("favsync.adapters_pixiv_wallabag.proxy_url", return_value=""):
            adapter = WallabagAdapter({})
            self.assertIs(adapter._session(), session)
            self.assertIs(adapter._session(), session)
            adapter.close()
            session.close.assert_called_once()
            self.assertIsNone(adapter._http_session)


if __name__ == "__main__":
    unittest.main()
