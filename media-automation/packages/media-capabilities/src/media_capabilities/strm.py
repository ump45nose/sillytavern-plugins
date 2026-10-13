"""STRM publication and read-only playback verification, separate from Emby state."""
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import json

import httpx


class P115StrmPublisher:
    def __init__(self, gateway, files, local_root):
        self.gateway, self.files, self.local_root = gateway, files, Path(local_root).resolve()

    def publish(self, job):
        directory = self.local_root / ("Movie" if job["unit"]["kind"] == "movie" else "TV_Show") / job["id"][:20]
        self.files.checked(directory, output=True)
        directory.mkdir(parents=True, exist_ok=True)
        journal = directory / ".mediaarchive.json"
        owned = json.loads(journal.read_text()) if journal.exists() else {}
        def checkpoint():
            temporary = journal.with_suffix(".tmp")
            temporary.write_text(json.dumps(owned), encoding="utf-8")
            temporary.replace(journal)
        data, artifacts = [], []
        for upload in job["uploads"].values():
            receipt = upload["receipt"]
            target = directory / (Path(receipt["name"]).stem + ".strm")
            if target.exists():
                entry = owned.get(str(receipt["id"]))
                if not target.is_file() or not entry or entry["path"] != str(target):
                    raise ValueError("STRM 目标存在且不属于本任务")
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if entry.get("digest") and entry["digest"] != digest:
                    raise ValueError("STRM 文件已被其他流程修改")
                entry["digest"] = digest
                artifacts.append({"path": str(target), "cloud_id": receipt["id"],
                                  "episode": upload["asset"].get("episode")})
                continue
            data.append({"id": receipt["id"], "name": receipt["name"], "sha1": receipt["sha1"],
                         "size": receipt["size"], "pick_code": receipt["pickcode"],
                         "pan_path": receipt["path"], "pan_media_path": str(Path(receipt["path"]).parent),
                         "local_path": str(directory), "media_server_refresh": False,
                         "scrape_metadata": False})
            artifacts.append({"path": str(target), "cloud_id": receipt["id"],
                              "episode": upload["asset"].get("episode")})
            owned[str(receipt["id"])] = {"path": str(target)}
        if data:
            checkpoint()
            self.gateway.create_strm(data)
        if not artifacts:
            raise ValueError("STRM 清单为空")
        for artifact in artifacts:
            target = Path(artifact["path"])
            owned[str(artifact["cloud_id"])]["digest"] = hashlib.sha256(target.read_bytes()).hexdigest()
        checkpoint()
        return artifacts

    def verify(self, artifacts):
        for artifact in artifacts:
            path = self.files.checked(artifact["path"], output=True)
            if path.stat().st_size > 16384:
                raise ValueError("STRM 内容超过限制")
            owned = json.loads((path.parent / ".mediaarchive.json").read_text())
            entry = owned.get(str(artifact["cloud_id"]))
            if not entry or entry.get("digest") != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError("STRM 文件归属或内容无法确认")
            lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
            if len(lines) != 1 or urlsplit(lines[0]).scheme not in {"http", "https"}:
                raise ValueError("STRM 不是单个 HTTP(S) 链接")
            url = lines[0]
            # Read a bounded sample; HTTP 200 alone is not playback evidence.
            with httpx.stream("GET", url, headers={"Range": "bytes=0-4095"},
                              timeout=30, follow_redirects=True) as response:
                response.raise_for_status()
                sample = next(response.iter_bytes(4096), b"")
                if not sample or "text/html" in response.headers.get("content-type", ""):
                    raise ValueError("STRM 返回空内容或网页")
            self.files.inspect_media(url)
