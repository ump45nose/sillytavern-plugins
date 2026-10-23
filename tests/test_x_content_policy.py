"""Only the verified nonfatal X author-policy warning may pass a scan."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from favsync.acquisition import collect_source
from favsync.adapters import XAdapter
from favsync.common import SyncError, command
from favsync.config import load
from favsync.engine import Engine
from favsync.sources import REGISTRY


POLICY_WARNING = (
    "[twitter][warning] u12345: '@fixture_author is temporarily unavailable "
    "because it violates the X Adult Content or Violent Content policy.'"
)
EVENTS = [[2, "", {"tweet_id": 123, "date": "2026-10-10T00:00:00+00:00",
                    "date_bookmarked": "2026-10-10T00:00:00+00:00",
                    "content": "fixture", "author": {}, "count": 0}]]


class XContentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = Path(self.temp.name) / "config.toml"
        config.write_text('state_dir="state"\n[x]\nusername="fixture"\n')
        self.cfg = load(config)
        Path(self.cfg["state_dir"]).mkdir()

    def process(self, diagnostics, events=EVENTS, returncode=0):
        def run(_argv, *, stdout, stderr, **_kwargs):
            stdout.write(json.dumps(events).encode())
            stderr.write(diagnostics.encode())
            return SimpleNamespace(returncode=returncode)
        return patch("favsync.common.subprocess.run", side_effect=run)

    def scan(self, stderr, events=EVENTS, returncode=0, source="x_likes"):
        with self.process(stderr, events, returncode):
            return XAdapter(self.cfg).scan(source)

    def test_verified_warning_preserves_complete_export_for_both_x_sources(self):
        for source in ("x_likes", "x_bookmarks"):
            with self.subTest(source=source):
                result = self.scan(POLICY_WARNING + "\n", source=source)
                self.assertTrue(result.complete)
                self.assertEqual(result.reason, "end")
                self.assertEqual([item["id"] for item in result.records], ["123"])

    def test_default_command_and_other_platforms_remain_strict(self):
        with self.process(POLICY_WARNING), self.assertRaisesRegex(SyncError, "content_unavailable"):
            command(["fixture"], 1)

    def test_complete_scan_clears_old_error_without_resetting_baseline(self):
        engine = Engine(self.cfg)
        self.addCleanup(engine.close)
        engine.store.source("x_likes", "personal")
        engine.store.update("x_likes", "personal", baseline_at=123,
                            scan_status="incomplete", error="content_unavailable")
        with self.process(POLICY_WARNING):
            self.assertTrue(collect_source(self.cfg, engine.store, engine.guard,
                REGISTRY["x_likes"], self.cfg["x_likes"], XAdapter(self.cfg)))
        source = engine.store.source("x_likes", "personal")
        self.assertEqual((source["scan_status"], source["error"], source["baseline_at"]),
                         ("complete", None, 123))

    def test_unknown_warning_still_fails(self):
        with self.assertRaisesRegex(SyncError, "scan_incomplete"):
            self.scan("[twitter][warning] Received Tweet results without 'core' data ... Retrying\n")

    def test_other_content_unavailable_warning_still_fails(self):
        with self.assertRaisesRegex(SyncError, "content_unavailable"):
            self.scan("[twitter][warning] timeline unavailable\n")

    def test_allowed_warning_cannot_hide_additional_warnings(self):
        with self.assertRaisesRegex(SyncError, "rate_limited"):
            self.scan(POLICY_WARNING + "\n[twitter][warning] 429 rate limit\n")

    def test_allowed_warning_cannot_hide_errors(self):
        with self.assertRaisesRegex(SyncError, "auth_required"):
            self.scan(POLICY_WARNING + "\n[twitter][error] 403 login required\n")

    def test_nonzero_exit_is_never_allowed(self):
        with self.assertRaisesRegex(SyncError, "content_unavailable"):
            self.scan(POLICY_WARNING, returncode=1)

    def test_terminal_export_error_still_fails(self):
        events = EVENTS + [[-1, {"error": "NotFoundError", "message": "timeline missing"}]]
        with self.assertRaisesRegex(SyncError, "content_unavailable"):
            self.scan(POLICY_WARNING, events)

    def test_incomplete_media_export_still_fails(self):
        events = [[2, "", {**EVENTS[0][-1], "count": 1}]]
        with self.assertRaisesRegex(SyncError, "incomplete_media_list"):
            self.scan(POLICY_WARNING, events)

    def test_warning_must_match_the_exact_verified_record(self):
        cases = (
            POLICY_WARNING.replace("[twitter]", "[pixiv]"),
            POLICY_WARNING.replace("Adult Content or Violent Content", "another"),
            POLICY_WARNING + " [error] unavailable",
        )
        for warning in cases:
            with self.subTest(warning=warning), self.assertRaisesRegex(SyncError, "content_unavailable"):
                self.scan(warning)


if __name__ == "__main__":
    unittest.main()
