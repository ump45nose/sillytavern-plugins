"""Check publication boundaries and refresh behavior without touching NAS files."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

import server


class QuietHandler(server.PreviewHandler):
    def log_message(self, *args):
        pass


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.base = Path(self.tmp.name)
        server.ROOT = self.base / "public"
        server.ROOT.mkdir()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, method="GET", headers=None):
        conn = HTTPConnection("127.0.0.1", self.http.server_port)
        conn.request(method, path, headers=headers or {})
        r = conn.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        conn.close()
        return result

    def test_directory_preview_and_no_listing(self):
        folder = server.ROOT / "design"
        folder.mkdir()
        (folder / "preview.html").write_text("preview")
        self.assertEqual(self.request("/design/")[2], b"preview")
        status, headers, _ = self.request("/design?mode=rp")
        self.assertEqual((status, headers["Location"]), (302, "/design/?mode=rp"))
        self.assertEqual(self.request("/")[0], 404)

    def test_private_files_traversal_and_symlinks(self):
        (server.ROOT / ".secret.html").write_text("private")
        (server.ROOT / "hidden-link.html").symlink_to(server.ROOT / ".secret.html")
        outside = self.base / "secret.html"
        outside.write_text("private")
        (server.ROOT / "linked.html").symlink_to(outside)
        folder = server.ROOT / "linked-index"
        folder.mkdir()
        (folder / "preview.html").symlink_to(outside)
        (server.ROOT / "source.py").write_text("private")
        for path in ("/.secret.html", "/%2esecret.html", "/../secret.html",
                     "/%2e%2e/secret.html", "/linked.html", "/linked-index/", "/hidden-link.html", "/source.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_refresh_and_head(self):
        target = server.ROOT / "index.html"
        for value in (b"first", b"second"):
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(value)
            tmp.replace(target)
            status, headers, data = self.request("/", headers={"If-Modified-Since": "Wed, 01 Jan 2100 00:00:00 GMT"})
            self.assertEqual((status, data), (200, value))
            self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
            self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        status, headers, data = self.request("/", "HEAD")
        self.assertEqual((status, data, headers["Content-Length"]), (200, b"", "6"))


if __name__ == "__main__":
    unittest.main()
