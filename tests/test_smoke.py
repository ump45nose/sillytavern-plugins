"""Bounded smoke checks for persistence, filtering and credential boundaries."""
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from favsync.adapters import parse_x, TelegramAdapter, XAdapter
from favsync.common import SyncError
from favsync.config import load, proxy_url, start_timestamp, telegram_config
from favsync.cookies import decrypt, netscape, sync
from favsync.engine import Engine


def post(item_id, assets=((1, "001.jpg"),), when=None):
    return {"id": str(item_id), "text": "原文\nhttps://example.com/仅保留文字", "assets": assets,
            "action_time": when if when is not None else time.time(),
            "locator": {"url": f"https://x.com/i/web/status/{item_id}"}}


class FakeAdapter:
    def __init__(self):
        self.records = []
        self.failure = None
        self.fail_download = set()
        self.downloads = []
        self.scans = 0

    def scan(self, source, cursor=0, start=None):
        self.scans += 1
        if self.failure:
            raise SyncError(self.failure)
        return self.records, None

    def download(self, item, asset, staging):
        key = (item["item_id"], asset["number"])
        if key in self.fail_download:
            raise SyncError("network_failure")
        self.downloads.append(key)
        result = staging / asset["filename"]
        result.write_bytes(b"fixture media bytes")
        return result


class Smoke(unittest.TestCase):
    def test_telegram_multiple_accounts_keep_separate_state_and_files(self):
        self.cfg["x_likes"]["enabled"] = False
        self.cfg["telegram"].update(enabled=True, start_date="2020-01-01", accounts=[{"account": "second"}])
        other = FakeAdapter()
        self.tg.records = [post(123)]
        other.records = [post(123)]
        with patch("favsync.engine.TelegramAdapter", return_value=other):
            self.assertTrue(self.engine.cycle())
        folders = Path(self.cfg["download_dir"]) / "Telegram"
        self.assertTrue(list(folders.glob("*_personal_123.jpg")))
        self.assertTrue(list(folders.glob("*_second_123.jpg")))
        self.assertEqual(self.engine.store.db.execute("SELECT count(*) FROM items").fetchone()[0], 2)
        adapter = TelegramAdapter(telegram_config(self.cfg, "second"))
        self.assertEqual(adapter.base()[-1], "second")

    def test_telegram_login_preserves_session_on_failure_and_backs_up_replace(self):
        adapter = TelegramAdapter(self.cfg)
        session = Path(self.cfg["state_dir"]) / "tdl/personal"
        session.parent.mkdir()
        session.write_bytes(b"old-session")
        with self.assertRaisesRegex(SyncError, "session_exists"):
            adapter.login("qr")
        with patch("favsync.adapters.sys.stdin.isatty", return_value=True), patch("favsync.adapters.sys.stdout.isatty", return_value=True):
            with patch("favsync.adapters.subprocess.call", return_value=1):
                self.assertEqual(adapter.login("qr", replace=True), 1)
            self.assertEqual(session.read_bytes(), b"old-session")
            def login(args):
                location = args[args.index("--storage") + 1].split("path=", 1)[1]
                (Path(location) / "personal").write_bytes(b"new-session")
                return 0
            with patch("favsync.adapters.subprocess.call", side_effect=login):
                self.assertEqual(adapter.login("code", replace=True), 0)
        self.assertEqual(session.read_bytes(), b"new-session")
        backups = list((Path(self.cfg["state_dir"]) / "session-backups").glob("personal-*.bak"))
        self.assertEqual(backups[0].read_bytes(), b"old-session")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        config = root / "config.toml"
        config.write_text('state_dir="state"\ndownload_dir="downloads"\n[x_likes]\nenabled=true\n[x]\nusername="fixture"\n')
        self.cfg = load(config)
        self.cfg["storage"] = {"min_free_bytes": 0, "resume_free_bytes": 0}
        self.x = FakeAdapter()
        self.tg = FakeAdapter()
        self.engine = Engine(self.cfg, {"x": self.x, "telegram": self.tg})
        Path(self.cfg["state_dir"], "x-cookies.txt").write_bytes(netscape({"cookie_data": {"x.com": [
            {"domain": ".x.com", "name": "auth_token", "value": "fixture-only"},
            {"domain": ".x.com", "name": "ct0", "value": "fixture-only"}]}}))

    def tearDown(self):
        self.engine.store.close()
        self.temp.cleanup()

    def test_likes_baseline_restart_new_failure_retry_and_shared_files(self):
        self.x.failure = "scan_incomplete"
        self.assertFalse(self.engine.cycle())
        self.assertIsNone(self.engine.store.source("x_likes", "personal")["baseline_at"])
        self.assertEqual(self.engine.store.db.execute("SELECT count(*) FROM seen").fetchone()[0], 0)
        self.x.failure = None
        self.x.records = [post(10)]
        self.assertTrue(self.engine.cycle())
        self.assertEqual(self.x.downloads, [])
        self.engine.store.close()
        self.engine = Engine(self.cfg, {"x": self.x, "telegram": self.tg})
        self.x.records.append(post(11, ((1, "001.jpg"), (2, "002.mp4"))))
        self.x.fail_download.add(("11", 2))
        self.assertFalse(self.engine.cycle())
        self.assertEqual(self.x.downloads, [("11", 1)])
        self.x.fail_download.clear()
        self.assertTrue(self.engine.cycle())
        self.assertEqual(self.x.downloads, [("11", 1), ("11", 2)])
        self.cfg["x_bookmarks"].update(enabled=True, start_date="2020-01-01")
        self.x.records = [post(11, ((1, "001.jpg"), (2, "002.mp4")))]
        self.engine.cycle()
        self.assertEqual(len(self.x.downloads), 2)
        self.assertEqual(self.engine.store.db.execute("SELECT count(*) FROM items").fetchone()[0], 1)
        seen = self.engine.store.db.execute("SELECT first_seen_at,baseline FROM seen WHERE source='x_likes' AND item_id='11'").fetchone()
        self.assertGreater(seen[0], 0)
        self.assertEqual(seen[1], 0)
        folder = Path(self.cfg["download_dir"]) / "Twitter"
        self.assertIn("原文", (folder / "收藏.md").read_text())
        self.assertTrue(list(folder.glob("*_personal_11_002.mp4")))

    def test_dates_empty_boundary_unknown_and_text_only(self):
        self.cfg["x_likes"]["enabled"] = False
        self.cfg["x_bookmarks"]["enabled"] = True
        self.engine.cycle()
        self.assertEqual(self.x.scans, 0)
        start = start_timestamp("2026-01-02", "Asia/Taipei")
        self.assertEqual(start, int(datetime(2026, 1, 1, 16, tzinfo=timezone.utc).timestamp()))
        self.cfg["x_bookmarks"]["start_date"] = "2026-01-02"
        unknown = post(4)
        unknown["action_time"] = None
        self.x.records = [post(1, when=start-1), post(2, when=start), post(3, assets=()), unknown]
        self.assertFalse(self.engine.cycle())
        ids = [r[0] for r in self.engine.store.db.execute("SELECT item_id FROM items ORDER BY item_id")]
        self.assertEqual(ids, ["2", "3"])
        self.assertIn("x:personal:3:end", (Path(self.cfg["download_dir"]) / "Twitter/收藏.md").read_text())

    def test_auth_pause_cookie_change_and_telegram_isolation(self):
        self.cfg["telegram"].update(enabled=True, start_date="2020-01-01")
        self.tg.records = [post(20, assets=())]
        self.x.failure = "auth_required"
        self.engine.cycle()
        scans = self.x.scans
        self.engine.cycle()
        self.assertEqual(self.x.scans, scans)
        self.assertEqual(self.tg.scans, 2)
        jar = Path(self.cfg["state_dir"]) / "x-cookies.txt"
        jar.write_text(jar.read_text().replace("fixture-only", "fixture-refreshed"))
        self.x.failure = None
        self.engine.cycle()
        self.assertEqual(self.x.scans, scans + 1)

    def test_gallery_error_even_when_process_exit_is_zero(self):
        with self.assertRaises(SyncError):
            parse_x([[-1, {"error": "AuthorizationError", "message": "fixture"}]])
        meta = {"tweet_id": 1, "content": "纯文字", "count": 0}
        self.assertEqual(parse_x([[2, meta]])[0]["text"], "纯文字")
        with self.assertRaises(SyncError):
            parse_x([[2, {**meta, "count": 2}]])

    def test_telegram_export_and_single_attachment_command_contract(self):
        adapter = TelegramAdapter(self.cfg)
        start = start_timestamp("2020-01-01", self.cfg["timezone"])
        def export_command(args, timeout):
            self.assertIn("--all", args)
            self.assertIn("--with-content", args)
            self.assertIn("--raw", args)
            Path(args[args.index("-o") + 1]).write_text(json.dumps({"id": 123, "messages": [
                {"id": 1, "date": start, "text": "照片配文", "file": "photo.jpg"},
                {"id": 2, "date": start+1, "text": "视频配文", "file": "video.mp4"},
                {"id": 3, "date": start+2, "text": "文档", "file": "archive.zip"},
                {"id": 4, "date": start+3, "text": "纯文字", "file": ""}]}))
        with patch("favsync.adapters.command", export_command):
            records, cursor = adapter.scan("telegram", start=start)
        self.assertEqual(cursor, 4)
        self.assertEqual([r["assets"] for r in records], [[(1, "001.jpg")], [(1, "001.mp4")], [(1, "001.zip")], []])
        item = {"locator": json.dumps(records[0]["locator"])}
        staging = Path(self.temp.name) / "stage"
        staging.mkdir()
        def download_command(args, timeout):
            self.assertNotIn("--group", args)
            export = json.loads(Path(args[args.index("-f")+1]).read_text())
            self.assertEqual(export["id"], 123)
            self.assertEqual(export["messages"][0]["id"], 1)
            self.assertTrue(export["messages"][0]["file"])
            (staging / "001.jpg").write_bytes(b"fixture")
        with patch("favsync.adapters.command", download_command):
            self.assertTrue(adapter.download(item, {"filename": "001.jpg"}, staging).is_file())

    def test_cookiecloud_both_ciphers_filter_and_failed_sync_keeps_cookie(self):
        payload = {"cookie_data": {"x.com": [
            {"domain": ".x.com", "name": "auth_token", "value": "fixture"},
            {"domain": ".x.com", "name": "ct0", "value": "fixture"}],
            "other": [{"domain": ".example.org", "name": "private", "value": "never-export"}]}}
        for method in ("legacy", "aes-128-cbc-fixed"):
            secret = hashlib.md5(b"fixture-id-fixture-password").hexdigest()[:16].encode()
            header = b""
            if method == "legacy":
                salt = b"12345678"
                header = b"Salted__" + salt
                material = previous = b""
                while len(material) < 48:
                    previous = hashlib.md5(previous + secret + salt).digest()
                    material += previous
                key, iv = material[:32], material[32:48]
            else:
                key, iv = secret, bytes(16)
            pad = padding.PKCS7(128).padder()
            padded = pad.update(json.dumps(payload).encode()) + pad.finalize()
            enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            envelope = {"crypto_type": method, "encrypted": base64.b64encode(header + enc.update(padded) + enc.finalize()).decode()}
            self.assertEqual(decrypt(envelope, "fixture-id", "fixture-password"), payload)
            self.assertEqual(decrypt({"encrypted": envelope["encrypted"]}, "fixture-id", "fixture-password"), payload)
        jar = netscape(payload)
        self.assertNotIn(b"never-export", jar)
        self.assertIn(b"auth_token", jar)
        target = Path(self.cfg["state_dir"]) / "x-cookies.txt"
        original = target.read_bytes()
        with self.assertRaises(SyncError):
            sync(self.cfg)  # Missing credentials, no network call.
        self.assertEqual(target.read_bytes(), original)

    def test_x_download_scope_configuration(self):
        with XAdapter(self.cfg).config_file() as path:
            x = json.loads(Path(path).read_text())["extractor"]["twitter"]
            for name in ("expand", "conversations", "quoted", "cards", "articles", "twitpic"):
                self.assertFalse(x[name])
            self.assertTrue(x["replies"])
            self.assertTrue(x["text-tweets"])
            self.assertEqual(x["proxy"], "socks5h://127.0.0.1:7890")
            self.assertFalse(x["proxy-env"])

    def test_proxy_default_and_per_application_override(self):
        with XAdapter(self.cfg).config_file() as path:
            self.assertEqual(json.loads(Path(path).read_text())["extractor"]["twitter"]["proxy"], "socks5h://127.0.0.1:7890")
        self.assertEqual(proxy_url(self.cfg, "telegram"), "socks5://127.0.0.1:7890")
        self.assertEqual(proxy_url(self.cfg, "future_platform"), "socks5://127.0.0.1:7890")
        self.assertIsNone(proxy_url(self.cfg, "cookiecloud"))
        base = TelegramAdapter(self.cfg).base()
        self.assertEqual(base[base.index("--proxy") + 1], "socks5://127.0.0.1:7890")
        self.cfg["proxy"]["applications"]["telegram"] = False
        self.assertNotIn("--proxy", TelegramAdapter(self.cfg).base())
        self.cfg["proxy"]["applications"]["x"] = False
        with XAdapter(self.cfg).config_file() as path:
            self.assertNotIn("proxy", json.loads(Path(path).read_text())["extractor"]["twitter"])


if __name__ == "__main__":
    unittest.main()
