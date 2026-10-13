"""Read-only design previews, served directly from mounted source directories."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
import os

ROOT = Path(__file__).with_name("public").resolve()
ASSETS = {".html", ".css", ".js", ".json", ".svg", ".png", ".jpg", ".jpeg",
          ".webp", ".gif", ".ico", ".woff", ".woff2", ".mp4", ".webm"}


class PreviewHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_head(self):
        url = urlsplit(self.path)
        if url.path == "/healthz":
            import io
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", "3")
            self.end_headers()
            return io.BytesIO(b"ok\n")
        decoded = unquote(url.path)
        parts = decoded.strip("/").split("/")
        if any(p.startswith(".") for p in parts) or "\x00" in decoded or "\\" in decoded:
            self.send_error(404)
            return None
        try:
            path = (ROOT / decoded.lstrip("/")).resolve()
            if any(p.startswith(".") for p in path.relative_to(ROOT).parts):
                raise ValueError("hidden target")
            if path.is_dir():
                if not url.path.endswith("/"):
                    self.send_response(302)
                    self.send_header("Location", quote(decoded, safe="/") + "/" +
                                     ("?" + url.query if url.query else ""))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                path = next((path / name for name in ("index.html", "preview.html")
                             if (path / name).is_file()), path)
                path = path.resolve()
                if any(p.startswith(".") for p in path.relative_to(ROOT).parts):
                    raise ValueError("hidden target")
            if path.suffix.lower() not in ASSETS or not path.is_file():
                self.send_error(404)
                return None
            stream = path.open("rb")
        except (OSError, ValueError):
            self.send_error(404)
            return None
        self.send_response(200)
        content_type = self.guess_type(str(path))
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(os.fstat(stream.fileno()).st_size))
        self.end_headers()
        return stream


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), partial(PreviewHandler, directory=str(ROOT)))
    print("Design previews listening on :8080", flush=True)
    server.serve_forever()
