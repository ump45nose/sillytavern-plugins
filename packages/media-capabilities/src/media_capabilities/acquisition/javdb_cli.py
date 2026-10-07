"""Small, replaceable adapter for the external javdb-cli JSON contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess


@dataclass(frozen=True)
class JavDbMagnet:
    number: str
    movie_id: str
    info_hash: str
    size_bytes: int
    magnet: str
    title: str = ""
    cnsub: bool = False
    hd: bool = False

    def dump(self) -> dict:
        return {
            "number": self.number, "movie_id": self.movie_id,
            "info_hash": self.info_hash, "size_bytes": self.size_bytes,
            "magnet": self.magnet, "title": self.title,
            "cnsub": self.cnsub, "hd": self.hd,
        }


def normalize_jav_number(value: str) -> str:
    text = (value or "").upper()
    fc2 = re.search(
        r"(?<![A-Z0-9])FC2(?:[-_. ]*PPV)?[-_. ]*(\\d{4,9})(?!\\d)", text)
    if fc2:
        return "FC2-PPV-" + fc2.group(1)
    match = re.search(
        r"(?<![A-Z0-9])([A-Z]{2,12})[-_. ]?(\\d{2,7})(?!\\d)", text)
    if not match:
        raise ValueError("无法识别 JAV 番号")
    return f"{match.group(1)}-{match.group(2)}"


def _truthy(value) -> bool:
    return value is True or value == 1 or str(value).casefold() in {"1", "true"}


class JavDbCli:
    """Run a managed javdb-cli binary without shell interpolation."""

    def __init__(self, binary: str = "javdb", timeout: int = 30):
        self.binary = binary
        self.timeout = max(3, min(int(timeout), 90))

    def health(self) -> dict:
        executable = self.binary if Path(self.binary).is_file() else shutil.which(self.binary)
        return {"status": "OK" if executable else "UNAVAILABLE",
                "binary": str(executable or self.binary)}

    def _run_json(self, args: list[str]) -> dict:
        if self.health()["status"] != "OK":
            raise RuntimeError("javdb-cli 不可用")
        result = subprocess.run([self.binary, *args, "--json"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=self.timeout, check=False)
        if result.returncode:
            raise RuntimeError("javdb-cli 请求失败")
        if len(result.stdout) > 8 * 1024 * 1024:
            raise ValueError("javdb-cli JSON 输出超过限制")
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("javdb-cli 返回的 JSON 无法解析") from exc
        if not isinstance(payload, dict):
            raise ValueError("javdb-cli 返回结构无效")
        return payload

    def magnets(self, number: str, *, limit: int = 12,
                cnsub: bool = False, hd: bool = False) -> list[JavDbMagnet]:
        code = normalize_jav_number(number)
        count = max(1, min(int(limit), 50))
        args = ["magnets", code]
        if cnsub:
            args.append("--cnsub")
        if hd:
            args.append("--hd")
        payload = self._run_json(args)
        movie_id = str(payload.get("movie_id") or "")
        rows = payload.get("magnets") or []
        if not isinstance(rows, list):
            raise ValueError("javdb-cli magnets 字段无效")
        result = []
        for row in rows[:count]:
            if not isinstance(row, dict):
                continue
            info_hash = str(row.get("hash") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{40}", info_hash):
                continue
            try:
                size_mib = int(float(row.get("size") or 0))
            except (TypeError, ValueError, OverflowError):
                size_mib = 0
            if size_mib <= 0:
                continue
            title = str(row.get("name") or row.get("title") or code)
            result.append(JavDbMagnet(
                number=code, movie_id=movie_id, info_hash=info_hash,
                size_bytes=size_mib * 1024 * 1024,
                magnet=f"magnet:?xt=urn:btih:{info_hash}", title=title,
                cnsub=_truthy(row.get("cnsub")), hd=_truthy(row.get("hd")),
            ))
        return result
