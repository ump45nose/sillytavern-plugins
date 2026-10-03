from __future__ import annotations

import gzip
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def http_server(monkeypatch):
    # Local-only fixtures must not inherit outbound proxy configuration.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/stall-headers":
                time.sleep(2)
                return
            if path.startswith("/status/"):
                self.send_response(int(path.rsplit("/", 1)[1]))
                self.end_headers()
                return
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/ok.mp3")
                self.end_headers()
                return
            if path == "/large-header":
                self.send_response(200)
                self.send_header("Content-Length", "100000")
                self.end_headers()
                return
            self.send_response(200)
            body = b"test-media-data"
            if path == "/gzip":
                body = gzip.compress(b"x" * 10000)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
            elif path == "/empty":
                body = b""
                self.send_header("Content-Length", "0")
            elif path == "/truncated":
                self.send_header("Content-Length", "100")
            elif path == "/stall-body":
                self.send_header("Content-Length", "100000")
                self.end_headers()
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(2)
                return
            elif path == "/trickle":
                self.end_headers()
                try:
                    for _ in range(40):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            elif path != "/no-length":
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def stub_ytdlp(tmp_path, monkeypatch):
    modules = tmp_path / "stub-modules"
    modules.mkdir()
    capture = tmp_path / "capture.json"
    stub = modules / "yt_dlp.py"
    stub.write_text('''
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
stage = pathlib.Path(args[args.index("--output") + 1]).parent
mode = args[-1]
info = {"args": args}
if "--cookies" in args:
    cookie = pathlib.Path(args[args.index("--cookies") + 1])
    info.update(cookie=str(cookie), cookie_mode=cookie.stat().st_mode & 0o777, cookie_content=cookie.read_text())
    cookie.write_text("modified by yt-dlp")
pathlib.Path(os.environ["STUB_CAPTURE"]).write_text(json.dumps(info))
if mode == "success":
    (stage / "source.m4a").write_bytes(b"media bytes")
elif mode == "empty":
    (stage / "source.m4a").touch()
elif mode == "none":
    pass
elif mode == "multiple":
    (stage / "source.m4a").write_bytes(b"one")
    (stage / "source.webm").write_bytes(b"two")
elif mode == "partial":
    (stage / "source.m4a.part").write_bytes(b"part")
elif mode == "bare-partial":
    (stage / "source.part").write_bytes(b"part")
elif mode == "nested":
    (stage / "nested").mkdir()
    (stage / "nested" / "source.m4a").write_bytes(b"media")
elif mode == "symlink":
    (stage / "source.m4a").symlink_to(os.environ["STUB_OUTSIDE"])
elif mode == "hardlink":
    os.link(os.environ["STUB_OUTSIDE"], stage / "source.m4a")
elif mode == "large":
    (stage / "source.m4a").write_bytes(b"x" * 10000)
elif mode == "aggregate-large":
    (stage / "source.m4a").write_bytes(b"x" * 80)
    (stage / "source.webm").write_bytes(b"x" * 80)
elif mode == "growing":
    with (stage / "source.m4a.part").open("wb") as f:
        for _ in range(1000):
            f.write(b"x" * 1000); f.flush(); time.sleep(0.02)
elif mode == "timeout" or mode == "leader-exit":
    subprocess.Popen([sys.executable, "-c", "import time, pathlib, os; time.sleep(1); pathlib.Path(os.environ['STUB_CHILD_MARKER']).write_text('survived')"])
    (stage / "source.m4a").write_bytes(b"media")
    if mode == "timeout":
        time.sleep(30)
elif mode == "log-flood":
    sys.stderr.write("secret-url " * 10000)
elif mode.startswith("error:"):
    (stage / "source.m4a.part").write_bytes(b"part")
    sys.stderr.write(mode[6:] + " https://secret.invalid/?token=PRIVATE cookie-secret")
    sys.exit(1)
''')
    monkeypatch.syspath_prepend(str(modules))
    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", str(modules) + (os.pathsep + existing if existing else ""))
    monkeypatch.setenv("STUB_CAPTURE", str(capture))
    marker = tmp_path / "child-survived"
    monkeypatch.setenv("STUB_CHILD_MARKER", str(marker))
    outside = tmp_path / "outside"
    outside.write_bytes(b"original outside bytes")
    monkeypatch.setenv("STUB_OUTSIDE", str(outside))
    return {"capture": capture, "outside": outside, "child_marker": marker}
